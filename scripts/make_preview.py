"""Build self-contained static preview pages (no server, no network) for design review.

Usage: .venv/bin/python scripts/make_preview.py OUT_DIR
Writes login, chat (commands + confirm card), chat-knowledge, admin-users, admin-targets, audit pages with CSS/JS inlined and canned demo data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "ember" / "static"

ANSWER = """Here is a minimal **ESP32 + SX1276** LoRa sender using the `arduino-LoRa` library. It sends a reading every 5 minutes and sleeps in between [1].

```cpp
#include <SPI.h>
#include <LoRa.h>

const int PIN_SS = 18, PIN_RST = 14, PIN_DIO0 = 26;   // TTGO LoRa32 pins
const long FREQ_HZ = 915E6;                           // US915
const uint64_t SLEEP_US = 5ULL * 60ULL * 1000000ULL;

void setup() {
  Serial.begin(115200);
  LoRa.setPins(PIN_SS, PIN_RST, PIN_DIO0);
  if (!LoRa.begin(FREQ_HZ)) {
    Serial.println("LoRa init failed");
    esp_deep_sleep(SLEEP_US);                          // retry after sleep
  }
  LoRa.setSpreadingFactor(9);
  float tempC = temperatureRead();
  LoRa.beginPacket();
  LoRa.print(tempC, 1);
  LoRa.endPacket();
  esp_deep_sleep(SLEEP_US);
}

void loop() {}
```

| Setting | Value | Why |
|---|---|---|
| SF | 9 | Good range vs. airtime |
| Bandwidth | 125 kHz | Default, widely compatible |

- Keep the antenna connected before powering the radio.
- Deep sleep draws about 10 uA on a bare ESP32 module [2]."""

SOURCES = [
    {"rank": 1, "score": 0.71, "title": "LoRa", "section": "Spreading factor", "source": "Wikipedia",
     "path": "A/LoRa", "text": "LoRa uses chirp spread spectrum. Higher spreading factors increase range and airtime..."},
    {"rank": 2, "score": 0.64, "title": "ESP32 deep sleep current", "section": "",
     "source": "electronics.stackexchange", "path": "q/1", "text": "In deep sleep with RTC timer wake, the chip draws ~10 uA..."},
]

DEMO = {
    "me": {"id": 1, "username": "matt", "is_admin": True},
    "models": {"models": [{"name": "gemma4:26b", "size": 1}, {"name": "llama3.1:8b", "size": 1},
                          {"name": "llama3.2-4k:latest", "size": 1}, {"name": "qwen3.5-9b-4k:latest", "size": 1}],
               "default": "qwen3.5-9b-4k:latest"},
    "kbs": {"kbs": [{"id": "none", "label": "No knowledge base", "description": "Model only"},
                    {"id": "nomad", "label": "Nomad", "description": "Offline library"}], "default": "nomad"},
    "chats": {"conversations": [
        {"id": 4, "title": "Flash LoRa sender to the ESP32 on the Mint", "model": "qwen3.5-9b-4k:latest", "kb": "none", "updated_at": 0},
        {"id": 1, "title": "ESP32 LoRa temperature sender", "model": "qwen3.5-9b-4k:latest", "kb": "nomad", "updated_at": 0},
        {"id": 2, "title": "Second-degree burn care", "model": "qwen3.5-9b-4k:latest", "kb": "nomad", "updated_at": 0},
        {"id": 3, "title": "Meshtastic channel settings", "model": "llama3.2-4k:latest", "kb": "none", "updated_at": 0}]},
    "conv": {"conversation": {"id": 1, "title": "ESP32 LoRa temperature sender", "model": "qwen3.5-9b-4k:latest",
                              "kb": "nomad"},
             "messages": [
                 {"role": "user", "content": "Write an ESP32 LoRa sender for an SX1276 that sends a temperature "
                  "reading every 5 minutes", "thinking": "", "sources": [], "model": ""},
                 {"role": "assistant", "content": ANSWER, "thinking": "", "sources": SOURCES,
                  "model": "qwen3.5-9b-4k:latest"}]},
    "users": {"users": [{"id": 1, "username": "matt", "is_admin": 1, "is_active": 1, "can_exec": 1},
                        {"id": 2, "username": "rain", "is_admin": 0, "is_active": 1, "can_exec": 0}]},
    "targets": {"exec": True, "master": True, "can_exec": True, "targets": [
        {"id": 1, "name": "P1", "kind": "local", "os": "linux", "host": ""},
        {"id": 2, "name": "Mint", "kind": "ssh", "os": "linux", "host": "192.168.1.120"},
        {"id": 3, "name": "Los Gatos", "kind": "ssh", "os": "windows", "host": "192.168.1.60"}]},
    "exec_admin": {"exec_enabled": True,
        "targets": [
            {"id": 1, "name": "P1", "kind": "local", "host": "", "port": 22, "username": "", "os": "linux",
             "credential_id": None, "host_fingerprint": "", "enabled": 1},
            {"id": 2, "name": "Mint", "kind": "ssh", "host": "192.168.1.120", "port": 22, "username": "matt",
             "os": "linux", "credential_id": 1, "host_fingerprint": "SHA256:q3J1mFv9kTzX0bLw7cYp2eH8sN4aR6uD5gK0oI1jM2E", "enabled": 1},
            {"id": 3, "name": "Los Gatos", "kind": "ssh", "host": "192.168.1.60", "port": 22, "username": "Matt",
             "os": "windows", "credential_id": 2, "host_fingerprint": "", "enabled": 1}],
        "credentials": [
            {"id": 1, "name": "mint key", "kind": "key", "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDemoDemoDemoDemoDemoDemoDemoDemoDemoDemo0 ember-mint-key"},
            {"id": 2, "name": "los gatos pw", "kind": "password", "public_key": ""}]},
    "audit": {"actions": [
        {"id": 3, "created_at": 1795642200, "username": "matt", "target_name": "Mint", "command": "esptool.py --port /dev/ttyUSB0 write_flash 0x10000 build/sender.bin", "risk": "risky", "status": "pending", "mode": "none", "exit_code": None},
        {"id": 2, "created_at": 1795642140, "username": "matt", "target_name": "Mint", "command": "arduino-cli compile -b esp32:esp32:esp32 ~/lora-sender", "risk": "safe", "status": "ran", "mode": "auto", "exit_code": 0},
        {"id": 1, "created_at": 1795642080, "username": "matt", "target_name": "Mint", "command": "ls /dev/ttyUSB* /dev/ttyACM*", "risk": "safe", "status": "ran", "mode": "auto", "exit_code": 0},
        {"id": 0, "created_at": 1795641000, "username": "rain", "target_name": "P1", "command": "rm -rf ~/old-builds", "risk": "risky", "status": "cancelled", "mode": "none", "exit_code": None}],
        "events": [
        {"at": 1795642000, "username": "matt", "event": "exec_master", "detail": "on"},
        {"at": 1795641900, "username": "matt", "event": "target_tested", "detail": "id=2 exit=0"},
        {"at": 1795641800, "username": "matt", "event": "credential_added", "detail": "id=1 kind=key"},
        {"at": 1795641700, "username": "matt", "event": "login_ok", "detail": ""}]},
    "exec_conv": {"conversation": {"id": 4, "title": "Flash LoRa sender to the ESP32 on the Mint", "model": "qwen3.5-9b-4k:latest",
                                   "kb": "none", "exec_on": 1, "target_id": 2},
        "messages": [{"id": 10, "role": "user", "content": "Compile ~/lora-sender for the ESP32 on the Mint and flash it", "thinking": "", "sources": [], "model": ""}],
        "actions": [
            {"id": 1, "after_message_id": 10, "target": "Mint", "command": "ls /dev/ttyUSB* /dev/ttyACM*", "reason": "Find the ESP32 serial port", "risk": "safe", "risk_reasons": [], "status": "ran", "mode": "auto", "exit_code": 0, "output": "/dev/ttyUSB0"},
            {"id": 2, "after_message_id": 10, "target": "Mint", "command": "arduino-cli compile -b esp32:esp32:esp32 --output-dir build ~/lora-sender", "reason": "Build the sketch", "risk": "safe", "risk_reasons": [], "status": "ran", "mode": "auto", "exit_code": 0, "output": "Sketch uses 284361 bytes (21%) of program storage space.\nGlobal variables use 21048 bytes (6%) of dynamic memory."},
            {"id": 3, "after_message_id": 10, "target": "Mint", "command": "esptool.py --port /dev/ttyUSB0 write_flash 0x10000 build/lora-sender.ino.bin", "reason": "Flash the new firmware to the board", "risk": "risky", "risk_reasons": ["flashes a device (esptool)"], "status": "pending", "mode": "none", "exit_code": None, "output": ""}]},
}

MOCK = """
window.EMBER_DEMO = (function () {
  var D = __DATA__;
  return {
    view: "__VIEW__", open: __OPEN__,
    api: async function (method, path) {
      if (path === "/api/version") return {version: "__VERSION__"};
      if (path === "/api/me") { if (this.view === "login") throw new Error("sign in required"); return D.me; }
      if (path === "/api/models") return D.models;
      if (path === "/api/kbs") return D.kbs;
      if (path === "/api/targets") return D.targets;
      if (path === "/api/admin/exec") return D.exec_admin;
      if (path === "/api/admin/audit") return D.audit;
      if (path === "/api/conversations/4") return D.exec_conv;
      if (path.indexOf("/api/conversations/") === 0) return D.conv;
      if (path.indexOf("/api/conversations") === 0) return D.chats;
      if (path === "/api/admin/users") return D.users;
      throw new Error("Preview only: nothing is saved.");
    }
  };
})();
"""


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def build(view: str, open_id: int | None, version: str) -> str:
    html = _read("index.html")
    css = _read("vendor/hljs-github-dark.min.css") + "\n" + _read("app.css")
    mock = (MOCK.replace("__DATA__", json.dumps(DEMO)).replace("__VIEW__", view)
            .replace("__OPEN__", json.dumps(open_id)).replace("__VERSION__", version))
    js = mock + "\n" + _read("vendor/highlight.min.js") + "\n" + _read("markdown.js") + "\n" + _read("app.js")
    js = js.replace("</script", "<\\/script")
    html = html.replace('<link rel="stylesheet" href="/static/vendor/hljs-github-dark.min.css">\n', "")
    html = html.replace('<link rel="stylesheet" href="/static/app.css">', "<style>\n" + css + "\n</style>")
    start = html.index('<script src="/static/vendor/highlight.min.js">')
    end = html.index("</body>")
    return html[:start] + "<script>\n" + js + "\n</script>\n" + html[end:]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sys.path.insert(0, str(ROOT))
    from ember import __version__

    out = Path(sys.argv[1]).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    pages = (("login", "login", None), ("chat", "chat", 4), ("chat-knowledge", "chat", 1), ("admin-users", "admin", 4),
             ("admin-targets", "targets", 4), ("audit", "audit", 4))
    for name, view, open_id in pages:
        (out / f"{name}.html").write_text(build(view, open_id, __version__), encoding="utf-8")
        print(out / f"{name}.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
