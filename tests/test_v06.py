"""v0.6.0: context budget, code index, project notes, rolling summary, trimmed build errors,
edit-by-diff, small-step mode, model speed sample, AMSAT pack."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ember import agent, auth, bench, budget, build_errors, code_index, context, notes, ollama, patching, projects
from ember.db import connect, init_db
from tests.conftest import USER_PW, login
from tests.test_exec import Script, _events, exec_client  # noqa: F401  (fixture)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_radio_kb  # noqa: E402

GIT = shutil.which("git") or "/usr/bin/git"


def git(*args: str) -> None:
    subprocess.run([GIT, "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, timeout=60)  # noqa: S603


MAIN_CPP = """#include <RadioLib.h>
#define PIN_LORA_NSS 8
#define PIN_LORA_BUSY 13

SX1262 radio = new Module(PIN_LORA_NSS, 14, 12, PIN_LORA_BUSY);

// Bring up the LoRa radio
int radioBegin() {
  int state = radio.begin(915.0);
  if (state != RADIOLIB_ERR_NONE) {
    return state;
  }
  return 0;
}

void startSoftAP() {
  WiFi.softAPConfig(local_ip, gateway, subnet);
  WiFi.softAP("Outpost");
}
"""
APP_PY = (
    "import os\n\n\ndef load_cfg(path):\n    return open(path).read()\n\n\n"
    "class Server:\n    def run(self):\n        pass\n"
)


# ---------- budget ----------
def test_budget_by_context_size() -> None:
    assert budget.context_size("qwen3.5-9b-8k:latest") == 8192
    assert budget.context_size("qwen3.5-9b-4k") == 4096
    assert budget.context_size("llama3.1:8b") == 4096
    for name in ("qwen3.5-9b-4k", "qwen3.5-9b-8k"):
        b = budget.plan(name)
        assert sum(b.tokens.values()) <= b.ctx
    assert budget.plan("x-8k").tokens["refs"] > budget.plan("x-4k").tokens["refs"] * 2
    u = budget.usage(budget.plan("x-4k"), {"system": "a" * 350})
    assert u["system"] == 100 and u["ctx"] == 4096 and u["total"] == 100 + u["reply"]
    assert budget.fit("line\n" * 100, 50).endswith("…")


# ---------- build errors ----------
def test_trim_gcc_with_source_lines() -> None:
    out = "Compiling .pio/build/x/src/main.cpp.o\n" * 40 + (
        "src/main.cpp:17:30: error: no matching function for call to 'WiFiAPClass::softAPConfig(IPAddress&)'\n"
        "   17 |   WiFi.softAPConfig(local_ip);\n"
        "src/main.cpp:17:30: error: no matching function for call to 'WiFiAPClass::softAPConfig(IPAddress&)'\n"
        "src/other.cpp:3:1: error: 'x' does not name a type\nsrc/third.cpp:9:1: error: boom\n"
        "*** [.pio/build/x/src/main.cpp.o] Error 1\n"
    )
    short = build_errors.trim(out, 1, lambda p: MAIN_CPP if p.endswith("main.cpp") else None)
    assert short and len(short) < len(out) // 2
    assert "src/main.cpp:17: no matching function" in short and ">   17|" in short
    assert "1 more errors hidden" in short and short.count("softAPConfig(IPAddress&)") == 1
    assert build_errors.trim(out, 0) is None and build_errors.trim("short", 1) is None


@pytest.mark.parametrize(
    ("line", "file", "num"),
    [
        (r"C:\src\Few\Program.cs(12,5): error CS0103: The name 'foo' does not exist", r"C:\src\Few\Program.cs", 12),
        ("lib/main.dart:8:3: Error: Undefined name 'bar'.", "lib/main.dart", 8),
        ("CMake Error at CMakeLists.txt:4 (find_package):", "CMakeLists.txt", 4),
    ],
)
def test_error_formats(line: str, file: str, num: int) -> None:
    errs = build_errors.find_errors("noise\n" * 5 + line + "\n  details here\n")
    assert errs and errs[0].file == file and errs[0].line == num


def test_trim_python_traceback() -> None:
    out = "x\n" * 400 + 'Traceback (most recent call last):\n  File "a.py", line 3\nValueError: bad\n'
    assert "ValueError: bad" in (build_errors.trim(out, 1) or "")


# ---------- patching ----------
def test_search_replace_and_unified() -> None:
    new = patching.apply(
        "main.cpp",
        MAIN_CPP,
        '<<<<<<< SEARCH\n  WiFi.softAP("Outpost");\n=======\n  WiFi.softAP("Outpost-2");\n>>>>>>> REPLACE',
    )
    assert 'softAP("Outpost-2")' in new
    diff = "@@ -10,3 +10,3 @@\n   if (state != RADIOLIB_ERR_NONE) {\n-    return state;\n+    return -1;\n   }\n"
    assert "return -1;" in patching.apply("main.cpp", MAIN_CPP, diff)
    assert patching.diff("f", "a\n", "b\n").startswith("--- f (now)")


@pytest.mark.parametrize(
    ("path", "patch", "why"),
    [
        ("m.cpp", "<<<<<<< SEARCH\nreturn\n=======\nx\n>>>>>>> REPLACE", "more than once"),
        ("m.cpp", "<<<<<<< SEARCH\nnot there\n=======\nx\n>>>>>>> REPLACE", "not found"),
        ("m.cpp", "<<<<<<< SEARCH\n  return 0;\n}\n=======\n  return 0;\n>>>>>>> REPLACE", "braces"),
        ("m.cpp", "@@ -1,1 +1,1 @@\n-nope\n+x\n", "doesn't match"),
        ("m.cpp", "", "empty"),
    ],
)
def test_patch_rejected(path: str, patch: str, why: str) -> None:
    with pytest.raises(patching.PatchError, match=why):
        patching.apply(path, MAIN_CPP, patch)


def test_python_edit_must_compile() -> None:
    with pytest.raises(patching.PatchError, match="syntax"):
        patching.apply("app.py", APP_PY, "<<<<<<< SEARCH\n        pass\n=======\n        if:\n>>>>>>> REPLACE")


# ---------- code index ----------
def test_chunking() -> None:
    names = [c.name for c in code_index.chunk_file("src/main.cpp", MAIN_CPP)]
    assert any("radioBegin" in n for n in names) and any("startSoftAP" in n for n in names)
    py = [c.name for c in code_index.chunk_file("app.py", APP_PY)]
    assert any("load_cfg" in n for n in py) and any("class Server" in n for n in py)
    assert code_index.chunk_file("README.md", "x") == []


def fake_embed(base: str, texts: list[str]) -> list[list[float]]:
    """Bag-of-words hashing embedder: deterministic, shares words -> similar vectors."""
    out = []
    for t in texts:
        v = [0.0] * 64
        for w in t.lower().replace("(", " ").replace(".", " ").split():
            v[int(hashlib.md5(w.encode(), usedforsecurity=False).hexdigest(), 16) % 64] += 1.0
        out.append(code_index._norm(v))
    return out


@pytest.fixture()
def mirror(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    (work / "src").mkdir(parents=True)
    (work / "src/main.cpp").write_text(MAIN_CPP)
    (work / "tools/app.py").parent.mkdir()
    (work / "tools/app.py").write_text(APP_PY)
    (work / "lib/gen").mkdir(parents=True)
    (work / "lib/gen/x.pb.dart").write_text("class X {}\n")
    (work / "README.md").write_text("# Outpost\n\nOffline campsite messaging over LoRa and Wi-Fi for phones.\n")
    (work / "platformio.ini").write_text("[env:heltec_v3_arduino3]\nboard = heltec_wifi_lora_32_V3\n")
    git("init", "-q", str(work))
    git("-C", str(work), "add", ".")
    git("-C", str(work), "commit", "-qm", "init")
    gitdir = tmp_path / "git"
    git("clone", "-q", "--mirror", str(work), str(gitdir / "Outpost.git"))
    monkeypatch.setattr(projects, "git_dir", lambda: gitdir)
    monkeypatch.setattr(code_index, "embed", fake_embed)
    return work


def test_index_build_search_refresh(settings: Any, mirror: Path) -> None:
    st = code_index.build(settings.data_dir, "http://127.0.0.1:1", "Outpost")
    assert st["state"] == "ready" and st["files"] == 2 and st["chunks"] >= 3
    hits = code_index.search(settings.data_dir, "", "Outpost", "why does radio.begin fail in radioBegin", 2000)
    assert hits[0]["path"] == "src/main.cpp" and "radioBegin" in hits[0]["text"]
    assert all(len(h["text"]) < 2000 for h in hits)
    assert code_index.search(settings.data_dir, "", "Outpost", "x", 0) == []
    assert not code_index._stale(settings.data_dir, "Outpost")
    (mirror / "src/main.cpp").write_text(MAIN_CPP + "\nint extra() {\n  return 2;\n}\n")
    git("-C", str(mirror), "commit", "-qam", "x")
    git("-C", str(projects.git_dir() / "Outpost.git"), "fetch", "-q", str(mirror), "+refs/heads/*:refs/heads/*")
    assert code_index._stale(settings.data_dir, "Outpost")
    assert code_index.build(settings.data_dir, "", "Outpost")["updated"] == 1
    assert "return 0;" in (code_index.file_text(settings.data_dir, "Outpost", "./src/main.cpp") or "")


def test_notes_draft_save(settings: Any, mirror: Path) -> None:
    d = notes.get(settings.data_dir, "Outpost")
    assert not d["saved"] and "Offline campsite messaging" in d["text"]
    assert "PIN_LORA_NSS=8" in d["text"] and "heltec_v3_arduino3" in d["text"]
    notes.save(settings.data_dir, "Outpost", "v1")
    notes.save(settings.data_dir, "Outpost", "v2")
    assert notes.get(settings.data_dir, "Outpost") == {"text": "v2", "saved": True}
    assert list(notes.path(settings.data_dir, "Outpost").parent.glob("*.bak-*"))
    with pytest.raises(ValueError):
        notes.save(settings.data_dir, "Nope", "x")


# ---------- rolling summary + context ----------
def test_rolling_summary(settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        auth.create_user(conn, "uu", "password-12345", is_admin=True)
        conn.execute(
            "INSERT INTO conversations(id, user_id, title, model, kb, created_at, updated_at) "
            "VALUES (1, 1, 't', 'm', 'none', 0, 0)"
        )
        for i in range(10):
            conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (1, ?, ?, 0)",
                ("user" if i % 2 == 0 else "assistant", f"message {i} " + "x" * 600),
            )
    calls: list[Any] = []
    monkeypatch.setattr(ollama, "complete", lambda *a, **k: calls.append(a) or "We set NSS to pin 8.")
    summary, past, did = context.history(settings.db_path, "", "m", 1, 3000)
    assert did and summary == "We set NSS to pin 8." and len(past) == context.KEEP_LAST
    assert past[-1]["content"].startswith("message 9")
    summary2, past2, did2 = context.history(settings.db_path, "", "m", 1, 3000)
    assert not did2 and summary2 == summary and len(calls) == 1


def test_prepare_with_project(settings: Any, mirror: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code_index.build(settings.data_dir, "", "Outpost")
    monkeypatch.setattr(code_index, "refresh_async", lambda *a, **k: False)
    init_db(settings.db_path)
    with connect(settings.db_path) as conn:
        auth.create_user(conn, "uu", "password-12345", is_admin=True)
        conn.execute(
            "INSERT INTO conversations(id, user_id, title, model, kb, created_at, updated_at) "
            "VALUES (1, 1, 't', 'm', 'none', 0, 0)"
        )
        conn.execute("INSERT INTO messages(conversation_id, role, content, created_at) VALUES (1, 'user', 'q', 0)")
    prep = context.prepare(
        settings.db_path,
        settings.data_dir,
        "",
        "qwen3.5-9b-4k",
        1,
        "Outpost",
        "softAPConfig in startSoftAP",
        "SYSTEM",
        None,
    )
    system = prep.messages[0]["content"]
    assert system.startswith("SYSTEM") and "Project notes (Outpost)" in system and "startSoftAP" in system
    assert prep.usage["ctx"] == 4096 and prep.usage["refs"] > 0 and prep.usage["total"] <= 4096


# ---------- agent: small steps, edit_file, update_notes, trimmed errors ----------
def test_parse_steps() -> None:
    assert agent.parse_steps("Plan:\n1. Read main.cpp\n2) Edit radioBegin\n- Build\nok") == [
        "Read main.cpp",
        "Edit radioBegin",
        "Build",
    ]


def test_small_steps_turn(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = exec_client
    monkeypatch.setattr(ollama, "complete", lambda *a, **k: "1. Check the folder\n2. Report back")
    script = Script([{"command": "echo step-one", "reason": "look"}, "Folder checked.", "Reported."])
    monkeypatch.setattr("ember.agent.stream_chat", script)
    conv = c.post("/api/conversations", json={"kb": "none"}).json()
    body = {
        "content": "Look at my project",
        "model": "qwen3.5-9b-4k",
        "kb": "none",
        "exec": True,
        "target_id": c.target_id,
        "small_steps": True,
    }  # type: ignore[attr-defined]
    ev = _events(c.post(f"/api/conversations/{conv['id']}/messages", json=body).text)
    plan = next(e for e in ev if e["type"] == "plan")
    assert plan["steps"] == ["Check the folder", "Report back"]
    done = [e for e in ev if e["type"] == "progress" and e["status"] == "done"]
    assert [d["index"] for d in done] == [0, 1] and ev[-1]["type"] == "done"
    # each step starts from a fresh, small context: system + one user message
    assert len(script.seen[0]) == 2 and "step 1 of 2" in script.seen[0][1]["content"]
    assert len(script.seen[2]) == 2 and "Folder checked." in script.seen[2][1]["content"]
    text = c.get(f"/api/conversations/{conv['id']}").json()["messages"][-1]["content"]
    assert "**Step 1/2: Check the folder**" in text and "**Step 2/2: Report back**" in text


def test_edit_file_tool(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:  # noqa: F811
    c = exec_client
    f = tmp_path / "main.cpp"
    f.write_text(MAIN_CPP)
    patch = "<<<<<<< SEARCH\n  return 0;\n}\n\nvoid=======\n>>>>>>> REPLACE"
    good = (
        "<<<<<<< SEARCH\n  int state = radio.begin(915.0);\n=======\n  int state = radio.begin(868.0);\n>>>>>>> REPLACE"
    )

    def tool(args: dict[str, Any]) -> Any:
        def gen(base: str, model: str, messages: Any, think: bool, tools: Any = None) -> Any:
            names = {t["function"]["name"] for t in tools or []}
            assert "edit_file" in names
            yield ("tool_calls", [{"function": {"name": "edit_file", "arguments": args}}])

        return gen

    calls = iter([tool({"path": str(f), "patch": patch}), tool({"path": str(f), "patch": good})])

    def fake(*a: Any, **k: Any) -> Any:
        try:
            yield from next(calls)(*a, **k)
        except StopIteration:
            yield ("content", "done")

    monkeypatch.setattr("ember.agent.stream_chat", fake)
    conv = c.post("/api/conversations", json={"kb": "none"}).json()
    body = {"content": "use 868", "model": "qwen3.5-9b-4k", "kb": "none", "exec": True, "target_id": c.target_id}  # type: ignore[attr-defined]
    ev = _events(c.post(f"/api/conversations/{conv['id']}/messages", json=body).text)
    confirm = next(e for e in ev if e["type"] == "confirm")["action"]
    assert confirm["command"] == f"edit {f}" and "+  int state = radio.begin(868.0);" in confirm["diff"]
    r = c.post(f"/api/actions/{confirm['id']}/decide", json={"run": True})
    assert r.status_code == 200
    assert "868.0" in f.read_text() and "915.0" in Path(str(f) + ".bak-ember").read_text()


def test_update_notes_tool_and_routes(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch, mirror: Path) -> None:  # noqa: F811
    c = exec_client
    monkeypatch.setattr(code_index, "refresh_async", lambda *a, **k: False)
    calls = [("update_notes", {"content": "# Outpost\nKey decisions: NSS on GPIO8."})]

    def fake(base: str, model: str, messages: Any, think: bool, tools: Any = None) -> Any:
        if calls:
            name, args = calls.pop(0)
            yield ("tool_calls", [{"function": {"name": name, "arguments": args}}])
        else:
            yield ("content", "ok")

    monkeypatch.setattr("ember.agent.stream_chat", fake)
    conv = c.post("/api/conversations", json={"kb": "none"}).json()
    body = {
        "content": "note it",
        "model": "qwen3.5-9b-4k",
        "kb": "none",
        "exec": True,
        "target_id": c.target_id,
        "project": "Outpost",
    }  # type: ignore[attr-defined]
    ev = _events(c.post(f"/api/conversations/{conv['id']}/messages", json=body).text)
    assert any(e["type"] == "budget" and e["usage"]["ctx"] == 4096 for e in ev)
    confirm = next(e for e in ev if e["type"] == "confirm")["action"]
    assert "+Key decisions: NSS on GPIO8." in confirm["diff"]
    c.post(f"/api/actions/{confirm['id']}/decide", json={"run": True})
    got = c.get("/api/projects/Outpost/notes").json()
    assert got["saved"] and "GPIO8" in got["text"]
    assert c.put("/api/admin/projects/Outpost/notes", json={"text": "edited"}).json()["text"] == "edited"
    assert c.get("/api/projects/Nope/notes").status_code == 404
    bad = dict(body, project="Nope")
    assert c.post(f"/api/conversations/{conv['id']}/messages", json=bad).status_code == 400
    c.post("/api/logout")
    login(c, "rain", USER_PW)
    assert c.put("/api/admin/projects/Outpost/notes", json={"text": "x"}).status_code == 403
    assert c.post("/api/admin/projects/Outpost/index").status_code == 403


def test_trimmed_error_goes_to_model(exec_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = exec_client
    noisy = "printf 'Compiling x\\n%.0s' $(seq 80); echo 'src/main.cpp:3:1: error: boom here'; exit 1"
    script = Script([{"command": noisy, "reason": "build"}, "Fix it."])
    monkeypatch.setattr("ember.agent.stream_chat", script)
    conv = c.post("/api/conversations", json={"kb": "none"}).json()
    body = {"content": "build", "model": "qwen3.5-9b-4k", "kb": "none", "exec": True, "target_id": c.target_id}  # type: ignore[attr-defined]
    ev = _events(c.post(f"/api/conversations/{conv['id']}/messages", json=body).text)
    confirm = next(e for e in ev if e["type"] == "confirm")["action"]
    c.post(f"/api/actions/{confirm['id']}/decide", json={"run": True})
    tool_msg = script.seen[-1][-1]["content"]
    assert "trimmed by Ember" in tool_msg and "src/main.cpp:3: boom here" in tool_msg
    assert tool_msg.count("Compiling x") <= 3


# ---------- models info / bench ----------
def test_models_info_sample(client: TestClient) -> None:
    login(client, "rain", USER_PW)
    d = client.get("/api/models/info").json()
    assert d["source"] == "sample shipped with Ember" and "T1000" in d["hardware"]
    r8 = bench.for_model(d, "qwen3.5-9b-8k:latest")
    assert r8 and r8["ctx"] == 8192 and r8["full"]["ttft_s"] > 0
    assert d["budgets"]["qwen3.5-9b-8k"]["ctx"] == 8192
    assert client.post("/api/admin/models/bench").status_code == 403


def test_bench_save_load(tmp_path: Path) -> None:
    bench.save(tmp_path, {"results": [{"model": "a"}], "date": "x"})
    assert bench.load(tmp_path)["source"] == "this machine"
    assert bench.ctx_tokens("qwen3.5-9b-8k") == 8192
    with pytest.raises(ValueError):
        bench._post("http://10.0.0.1:11434", "/api/ps", {})


# ---------- AMSAT pack ----------
def test_amsat_parsers() -> None:
    tle = "ISS (ZARYA)\n1 25544U 98067A   26329.5  .0001  00000-0  1-3 0  9993\n2 25544  51.6 1 2 3 4 15.5 1\n"
    secs = fetch_radio_kb.tle_sections(tle, "CelesTrak")
    assert secs[0][0] == "TLE ISS (ZARYA)" and "1 25544U" in secs[0][1]
    data = {
        "satellites": [
            {"sat_id": "A", "name": "RS-44", "norad_cat_id": 44909, "status": "in orbit"},
            {"sat_id": "B", "name": "DEAD", "status": "re-entered"},
        ],
        "transmitters": [
            {
                "sat_id": "A",
                "alive": True,
                "status": "active",
                "service": "Amateur",
                "description": "Mode V/U",
                "downlink_low": 435610000,
                "downlink_high": 435670000,
                "uplink_low": 145935000,
                "uplink_high": 145995000,
                "mode": "USB",
                "invert": True,
            },
            {"sat_id": "B", "alive": True, "status": "active", "service": "Amateur"},
        ],
    }
    out = fetch_radio_kb.satnogs_sections(data)
    assert len(out) == 1 and "435.6100-435.6700" in out[0][1] and "inverting" in out[0][1]
    roff = ".TH RIGCTLD 1\n.SH NAME\nrigctld \\- radio control daemon\n.SH OPTIONS\n.B \\-m\nmodel\n"
    assert fetch_radio_kb.roff_text(roff)[0][0] == "NAME"
    ids = {s["id"] for s in fetch_radio_kb.all_sources()}
    assert {"tle-celestrak-amateur", "satnogs-transmitters", "hamlib-rotctld", "phased-array-guide"} <= ids
    for s in fetch_radio_kb.all_sources():
        if s["kind"] == "local":
            assert (Path(fetch_radio_kb.REPO) / s["url"]).is_file()


def test_amsat_guides_cover_topics() -> None:
    root = Path(__file__).resolve().parent.parent / "docs/amsat"
    text = (root / "satellite-ops.md").read_text() + (root / "phased-array-tracking.md").read_text()
    for word in (
        "rigctld",
        "rotctld",
        "Gpredict",
        "Doppler",
        "Monopulse",
        "Alpha-beta",
        "Kalman",
        "FMCW",
        "Make-before-break",
        "true time delay",
        "IC-7300",
    ):
        assert word.lower() in text.lower(), word
    json.dumps(text)


def test_cued_steering_and_yagi_guides() -> None:
    root = Path(__file__).resolve().parent.parent / "docs/amsat"
    cued = (root / "radar-cued-steering.md").read_text().lower()
    for word in ("ads-b", "aircraft scatter", "latency", "enu", "msk144", "arrl vhf", "part 97"):
        assert word in cued, word
    yagi = (root / "yagi-reference.md").read_text().lower()
    for word in ("144.2 mhz", "432.1 mhz", "stacking", "boom correction", "cross-yagi", "xnec2c", "gw 1 21"):
        assert word in yagi, word
    ids = {s["id"] for s in fetch_radio_kb.all_sources()}
    assert {"radar-cued-guide", "yagi-guide", "xnec2c-readme", "dump1090-fa-readme", "wiki-yagi-uda-antenna"} <= ids
