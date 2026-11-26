"""Radio (CHIRP) and 3D printer (CC2) routes for the Radio and Printer screens.

Every operation needs command running to be allowed (master switch + user),
is written to the actions log (shown in Audit), and anything that writes to a
radio or starts/cancels a print requires `confirm: true` from the UI dialog.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ember import parts, printer, radio, roles, targets, tools
from ember.db import audit, connect, now
from ember.deps import User, _db
from ember.runner import (
    RunResult,
    Secret,
    TargetSpec,
    cap,
    check_remote_path,
    fetch_file,
    push_file,
    redact,
    run_local,
    run_ssh,
)
from ember.vault import Vault, VaultError

RADIO_TIMEOUT_SEC = 240


class RadioIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    model_key: str = Field(max_length=40)
    port: str = Field(default="", max_length=240)
    notes: str = Field(default="", max_length=300)


class HostIn(BaseModel):
    host_id: int = Field(default=0, ge=0)
    port: str = Field(default="", max_length=240)


class EditIn(BaseModel):
    edits: list[dict[str, Any]] = Field(max_length=200)


class UploadIn(HostIn):
    confirm: bool = False


class PrinterIn(BaseModel):
    target_id: int = Field(default=0, ge=0)
    file: str = Field(default="", max_length=120)
    confirm: bool = False


class SliceIn(BaseModel):
    build_host_id: int = Field(default=0, ge=0)
    model: str = Field(max_length=300)
    nozzle: str = Field(default="0.4", max_length=4)
    process: str = Field(default="", max_length=80)
    filament: str = Field(default="", max_length=80)
    outdir: str = Field(default="ember-prints", max_length=200)


class PrintUploadIn(PrinterIn):
    build_host_id: int = Field(default=0, ge=0)
    path: str = Field(max_length=300)


def _settings(request: Request) -> Any:
    return request.app.state.settings


def _vault(request: Request) -> Vault:
    vault: Vault = request.app.state.vault
    return vault


def _require_exec(conn: sqlite3.Connection, user_id: int) -> None:
    if not tools.exec_allowed(conn, user_id):
        raise HTTPException(status_code=403, detail="command running is off (admin switch or your account)")


def _host(conn: sqlite3.Connection, vault: Vault, role: str, host_id: int) -> tuple[TargetSpec, Secret | None]:
    target_id = roles.active_host(conn, role, host_id or None)
    if not target_id:
        raise HTTPException(status_code=400, detail=f"no {role} host is set (Admin > Targets > roles)")
    try:
        return targets.resolve(conn, vault, target_id, for_commands=role != "printer")
    except (ValueError, VaultError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run(spec: TargetSpec, secret: Secret | None, command: str) -> RunResult:
    if spec.kind == "local":
        return run_local(command, RADIO_TIMEOUT_SEC)
    return run_ssh(spec, secret, command, RADIO_TIMEOUT_SEC)


def _log(
    request: Request,
    user_id: int,
    spec: TargetSpec,
    kind: str,
    command: str,
    risky: bool,
    result: RunResult,
    secret: Secret | None,
) -> str:
    """Write the operation to the actions log; return redacted output for the UI."""
    body = result.output + (f"\n[ember] {result.error}" if result.error else "")
    out = cap(redact(body, [secret.value] if secret else []), 8000)
    with connect(_db(request)) as conn:
        conn.execute(
            "INSERT INTO actions(conversation_id, user_id, target_id, target_name, command, risk, risk_reasons, "
            "status, mode, exit_code, output, kind, created_at, finished_at) "
            "VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                spec.id,
                spec.name,
                command[:2000],
                "risky" if risky else "safe",
                "writes to a device" if risky else "",
                "ran" if result.exit_code == 0 else "failed",
                "confirmed" if risky else "auto",
                result.exit_code,
                out,
                kind,
                now(),
                now(),
            ),
        )
        if result.new_fingerprint:
            targets.remember_fingerprint(conn, spec.id, result.new_fingerprint)
    return out


def _radio_row(conn: sqlite3.Connection, radio_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM radios WHERE id = ?", (radio_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="no such radio")
    found: sqlite3.Row = row
    return found


def _fail(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc)[:300])


def register_radio_routes(app: FastAPI) -> None:  # noqa: C901
    @app.get("/api/radio")
    def radio_home(user: User, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            return {
                "models": [m.__dict__ for m in radio.MODELS.values()],
                "radios": radio.list_radios(conn),
                "hosts": roles.candidates(conn, "radio"),
                "active": roles.active_host(conn, "radio", None),
                "helper": radio.helper_available(),
            }

    @app.post("/api/radio/radios")
    def add_radio(body: RadioIn, user: User, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            try:
                radio_id = radio.add_radio(conn, body.name, body.model_key, body.port, body.notes)
            except radio.RadioError as exc:
                raise _fail(exc) from exc
            audit(conn, user["id"], "radio_added", f"id={radio_id} model={body.model_key}")
        return {"id": radio_id}

    @app.post("/api/radio/ports")
    def radio_ports(body: HostIn, user: User, request: Request) -> dict[str, Any]:
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            spec, secret = _host(conn, _vault(request), "radio", body.host_id)
        command = radio.ports_command(spec.os)
        result = _run(spec, secret, command)
        out = _log(request, user["id"], spec, "radio_ports", command, False, result, secret)
        return {"host": spec.name, "ports": radio.parse_ports(result.output, spec.os), "output": out}

    @app.post("/api/radio/radios/{radio_id}/backup")
    def radio_backup(radio_id: int, body: HostIn, user: User, request: Request) -> dict[str, Any]:
        """Read the radio (always safe) and store the image as a backup on the P1."""
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            row = _radio_row(conn, radio_id)
            spec, secret = _host(conn, _vault(request), "radio", body.host_id)
        model = radio.get_model(str(row["model_key"]))
        port = body.port or str(row["port"])
        try:
            if model.mode == "live":
                return _live_snapshot(request, user["id"], spec, secret, model, port, radio_id)
            remote = radio.remote_file(radio_id, f"backup-{now()}", spec.os)
            command = radio.download_command(model, port, remote, spec.os)
        except radio.RadioError as exc:
            raise _fail(exc) from exc
        result = _run(spec, secret, f"CHIRP_TESTENV=1 {command}" if spec.os != "windows" else command)
        out = _log(request, user["id"], spec, "radio_download", command, False, result, secret)
        if result.exit_code != 0:
            raise HTTPException(status_code=502, detail=f"download failed: {out[-600:]}")
        item = _pull_image(request, user["id"], spec, secret, radio_id, remote, "backup", None, "read from radio")
        return {**item, "output": out}

    @app.get("/api/radio/images/{image_id}/channels")
    def radio_channels(image_id: int, user: User, request: Request) -> dict[str, Any]:
        settings = _settings(request)
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            try:
                path, row = radio.image_path(conn, settings.data_dir, image_id)
                model = radio.get_model(str(row["model_key"]))
                parent = int(row["parent_id"] or 0)
                parent_path = radio.image_path(conn, settings.data_dir, parent)[0] if parent else None
            except radio.RadioError as exc:
                raise _fail(exc) from exc
        try:
            if row["kind"] == "snapshot":
                return {"channels": [], "text": path.read_text(errors="replace")[:20000], "diff": []}
            chans = radio.channels(model, path)
            diff = radio.diff_channels(radio.channels(model, parent_path), chans) if parent_path else []
        except radio.RadioError as exc:
            raise _fail(exc) from exc
        return {"channels": chans, "diff": diff}

    @app.post("/api/radio/images/{image_id}/edit")
    def radio_edit(image_id: int, body: EditIn, user: User, request: Request) -> dict[str, Any]:
        """Apply channel edits to a copy; the original image is never changed."""
        settings = _settings(request)
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            try:
                path, row = radio.image_path(conn, settings.data_dir, image_id)
                model = radio.get_model(str(row["model_key"]))
            except radio.RadioError as exc:
                raise _fail(exc) from exc
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "edited.img"
            try:
                old = radio.channels(model, path)
                new = radio.apply_edits(model, path, out, body.edits)
            except radio.RadioError as exc:
                raise _fail(exc) from exc
            with connect(_db(request)) as conn:
                item = radio.store_image(
                    conn,
                    settings.data_dir,
                    int(row["radio_id"]),
                    out,
                    "edited",
                    image_id,
                    f"{len(body.edits)} edit(s)",
                    user["id"],
                )
                audit(conn, user["id"], "radio_edited", f"image={item['id']} from={image_id}")
        return {**item, "diff": radio.diff_channels(old, new)}

    @app.post("/api/radio/images/{image_id}/upload")
    def radio_upload(image_id: int, body: UploadIn, user: User, request: Request) -> dict[str, Any]:
        """Write an image to the radio. Needs confirm=true. A fresh backup is read first."""
        if not body.confirm:
            raise HTTPException(status_code=400, detail="uploading to a radio needs confirmation")
        settings = _settings(request)
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            try:
                path, row = radio.image_path(conn, settings.data_dir, image_id)
                model = radio.get_model(str(row["model_key"]))
            except radio.RadioError as exc:
                raise _fail(exc) from exc
            radio_row = _radio_row(conn, int(row["radio_id"]))
            spec, secret = _host(conn, _vault(request), "radio", body.host_id)
        radio_id = int(row["radio_id"])
        if model.mode != "clone":
            raise HTTPException(status_code=400, detail=model.note)
        stamp = now()
        new_remote = radio.remote_file(radio_id, f"upload-{stamp}", spec.os)
        pre_remote = radio.remote_file(radio_id, f"preupload-{stamp}", spec.os)
        sent = push_file(spec, secret, path, new_remote)
        if not sent.ok:
            raise HTTPException(status_code=502, detail=f"could not copy image to {spec.name}: {sent.error}")
        try:
            command = radio.upload_command(model, body.port or str(radio_row["port"]), pre_remote, new_remote, spec.os)
        except radio.RadioError as exc:
            raise _fail(exc) from exc
        result = _run(
            spec, secret, f"CHIRP_TESTENV=1; export CHIRP_TESTENV; {command}" if spec.os != "windows" else command
        )
        out = _log(request, user["id"], spec, "radio_upload", command, True, result, secret)
        backup: dict[str, Any] = {}
        try:
            backup = _pull_image(
                request,
                user["id"],
                spec,
                secret,
                radio_id,
                pre_remote,
                "backup",
                None,
                "automatic backup before upload",
            )
        except HTTPException:
            backup = {}
        with connect(_db(request)) as conn:
            audit(conn, user["id"], "radio_upload", f"image={image_id} exit={result.exit_code}")
            if result.exit_code == 0:
                conn.execute(
                    "INSERT INTO radio_images(radio_id, kind, file_name, sha256, size, parent_id, note, user_id, "
                    "created_at) VALUES (?, 'uploaded', ?, ?, ?, ?, ?, ?, ?)",
                    (
                        radio_id,
                        row["file_name"],
                        row["sha256"],
                        row["size"],
                        image_id,
                        f"uploaded via {spec.name}",
                        user["id"],
                        now(),
                    ),
                )
        if result.exit_code != 0:
            raise HTTPException(status_code=502, detail=f"upload failed: {out[-600:]}")
        return {"ok": True, "backup": backup, "output": out}


def _pull_image(
    request: Request,
    user_id: int,
    spec: TargetSpec,
    secret: Secret | None,
    radio_id: int,
    remote: str,
    kind: str,
    parent: int | None,
    note: str,
) -> dict[str, Any]:
    settings = _settings(request)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "radio.img"
        got = fetch_file(spec, secret, remote, local, radio.MAX_IMAGE_BYTES)
        if not got.ok:
            raise HTTPException(status_code=502, detail=f"could not copy the image back: {got.error}")
        with connect(_db(request)) as conn:
            try:
                return radio.store_image(conn, settings.data_dir, radio_id, local, kind, parent, note, user_id)
            except radio.RadioError as exc:
                raise _fail(exc) from exc


def _live_snapshot(
    request: Request,
    user_id: int,
    spec: TargetSpec,
    secret: Secret | None,
    model: radio.RadioModel,
    port: str,
    radio_id: int,
) -> dict[str, Any]:
    """IC-7300: no clone image; store the channel listing as a text snapshot."""
    command = radio.live_list_command(model, port)
    result = _run(spec, secret, f"CHIRP_TESTENV=1 {command}" if spec.os != "windows" else command)
    out = _log(request, user_id, spec, "radio_snapshot", command, False, result, secret)
    if result.exit_code != 0:
        raise HTTPException(status_code=502, detail=f"read failed: {out[-600:]}")
    settings = _settings(request)
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "snapshot.txt"
        local.write_text(result.output, encoding="utf-8")
        with connect(_db(request)) as conn:
            item = radio.store_image(
                conn, settings.data_dir, radio_id, local, "snapshot", None, "channel listing (live radio)", user_id
            )
    return {**item, "output": out}


def register_printer_routes(app: FastAPI) -> None:
    def printer_spec(request: Request, user_id: int, target_id: int) -> tuple[TargetSpec, printer.PrinterSpec]:
        with connect(_db(request)) as conn:
            _require_exec(conn, user_id)
            spec, secret = _host(conn, _vault(request), "printer", target_id)
        if spec.kind != "printer":
            raise HTTPException(status_code=400, detail="that target is not a printer")
        return spec, printer.PrinterSpec(spec.host, secret.value if secret else "")

    def done(
        request: Request,
        user_id: int,
        spec: TargetSpec,
        kind: str,
        text: str,
        risky: bool,
        result: dict[str, Any] | None,
        error: str,
    ) -> None:
        run = RunResult(0 if result is not None else None, json.dumps(result or {})[:4000], error)
        _log(request, user_id, spec, kind, text, risky, run, None)

    @app.post("/api/printer/{action}")
    def printer_action(action: str, body: PrinterIn, user: User, request: Request) -> dict[str, Any]:
        if action not in printer.ACTIONS:
            raise HTTPException(status_code=404, detail="unknown printer action")
        if action in printer.CONFIRM_ACTIONS and not body.confirm:
            raise HTTPException(status_code=400, detail=f"'{action}' needs confirmation")
        spec, pspec = printer_spec(request, user["id"], body.target_id)
        try:
            result = printer.run_action(pspec, action, body.file)
        except (printer.PrinterError, OSError, ValueError) as exc:
            if action != "status":
                done(request, user["id"], spec, "printer", f"printer {action} {body.file}", True, None, str(exc))
            raise _fail(exc) from exc
        if action != "status":  # status is polled; don't flood the log
            done(
                request,
                user["id"],
                spec,
                "printer",
                f"printer {action} {body.file}".strip(),
                action in printer.CONFIRM_ACTIONS,
                result,
                "",
            )
        return {"printer": spec.name, "result": result}

    @app.post("/api/printer-slice")
    def printer_slice(body: SliceIn, user: User, request: Request) -> dict[str, Any]:
        """Slice a model on the build host with OrcaSlicer + CC2 profiles (no printer contact)."""
        with connect(_db(request)) as conn:
            _require_exec(conn, user["id"])
            build, secret = _host(conn, _vault(request), "build", body.build_host_id)
        try:
            model = check_remote_path(body.model)
            outdir = check_remote_path(body.outdir)
            command = printer.slice_command(build.os, model, body.nozzle, body.process, body.filament, outdir)
        except (printer.PrinterError, ValueError) as exc:
            raise _fail(exc) from exc
        result = _run(build, secret, command)
        out = _log(request, user["id"], build, "slice", command, False, result, secret)
        if result.exit_code != 0:
            raise HTTPException(status_code=502, detail=f"slicing failed: {out[-600:]}")
        sep = "\\" if build.os == "windows" else "/"
        return {"host": build.name, "gcode": f"{outdir}{sep}plate_1.gcode", "output": out[-2000:]}

    @app.post("/api/printer-upload")
    def printer_upload(body: PrintUploadIn, user: User, request: Request) -> dict[str, Any]:
        """Copy a sliced .gcode from the build host to the printer (does not start it)."""
        if not body.confirm:
            raise HTTPException(status_code=400, detail="sending a file to the printer needs confirmation")
        spec, pspec = printer_spec(request, user["id"], body.target_id)
        with connect(_db(request)) as conn:
            build, secret = _host(conn, _vault(request), "build", body.build_host_id)
        name = Path(body.path.replace("\\", "/")).name
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "job.gcode"
            got = fetch_file(build, secret, body.path, local, printer.MAX_GCODE_BYTES)
            if not got.ok:
                raise HTTPException(status_code=502, detail=f"could not read {body.path} on {build.name}: {got.error}")
            try:
                result = printer.upload(pspec, local, body.file or name)
            except (printer.PrinterError, OSError, ValueError) as exc:
                done(request, user["id"], spec, "printer", f"printer upload {name}", True, None, str(exc))
                raise _fail(exc) from exc
        done(request, user["id"], spec, "printer", f"printer upload {name}", True, result, "")
        return {"printer": spec.name, "result": result}


class PartSliceIn(BaseModel):
    file: str = Field(max_length=120)
    build_host_id: int = Field(default=0, ge=0)
    nozzle: str = Field(default="0.4", max_length=4)
    process: str = Field(default="", max_length=80)
    filament: str = Field(default="", max_length=80)


def register_parts_routes(app: FastAPI) -> None:
    @app.get("/api/parts")
    def parts_search(user: User, request: Request, q: str = "", limit: int = 30) -> dict[str, Any]:
        data_dir = _settings(request).data_dir
        conn = parts.open_db(data_dir)
        try:
            return {
                "results": parts.search(conn, q[:200], max(1, min(limit, 50))),
                "stats": parts.stats(conn, data_dir),
            }
        finally:
            conn.close()

    @app.get("/api/parts/{part_id}/files/{name}")
    def parts_file(part_id: int, name: str, user: User, request: Request) -> FileResponse:
        data_dir = _settings(request).data_dir
        conn = parts.open_db(data_dir)
        try:
            path = parts.part_file(data_dir, conn, part_id, name)
        except parts.PartsError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            conn.close()
        return FileResponse(path, filename=name, media_type="application/octet-stream")

    @app.post("/api/parts/{part_id}/slice")
    def parts_slice(part_id: int, body: PartSliceIn, user: User, request: Request) -> dict[str, Any]:
        """Copy a library model to the build host and slice it for the CC2. Sending/starting is separate."""
        data_dir = _settings(request).data_dir
        conn = parts.open_db(data_dir)
        try:
            path = parts.part_file(data_dir, conn, part_id, body.file)
        except parts.PartsError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            conn.close()
        if path.suffix.lower() == ".scad":
            raise HTTPException(status_code=400, detail="pick an STL/3MF/STEP file (SCAD is the editable source)")
        with connect(_db(request)) as dbc:
            _require_exec(dbc, user["id"])
            build, secret = _host(dbc, _vault(request), "build", body.build_host_id)
        sep = "\\" if build.os == "windows" else "/"
        remote = f"ember-prints{sep}part{part_id}{sep}{path.name}"
        sent = push_file(build, secret, path, remote)
        if not sent.ok:
            raise HTTPException(status_code=502, detail=f"could not copy to {build.name}: {sent.error}")
        outdir = f"ember-prints{sep}part{part_id}{sep}out"
        try:
            command = printer.slice_command(build.os, remote, body.nozzle, body.process, body.filament, outdir)
        except printer.PrinterError as exc:
            raise _fail(exc) from exc
        result = _run(build, secret, command)
        out = _log(request, user["id"], build, "slice", command, False, result, secret)
        if result.exit_code != 0:
            raise HTTPException(status_code=502, detail=f"slicing failed: {out[-600:]}")
        return {"host": build.name, "gcode": f"{outdir}{sep}plate_1.gcode", "output": out[-1500:]}


def register_device_routes(app: FastAPI) -> None:
    register_radio_routes(app)
    register_printer_routes(app)
    register_parts_routes(app)
