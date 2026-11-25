"""Phase 2 hook: command execution on the P1 and over SSH. NOT ACTIVE in phase 1.

Planned design (kept here so phase 2 slots in cleanly):
- Targets: an admin-editable list (name, host, user, port, key reference). SSH keys
  live in ~/.config/ember/keys (0600), never in the database export or the repo;
  any saved password is encrypted at rest.
- Master switch: execution is off unless an admin turns it on (EXEC_ENABLED below
  becomes a DB setting). Off means the model is never offered tools.
- Risk check: an allowlist of read-only commands runs directly; anything else
  (writes, rm, flashing, sudo, package installs, network changes) needs the user to
  click Confirm in the chat.
- Every run is written to the audit table (who, target, command, exit code), and
  commands use argument lists with timeouts, never shell=True.
"""

from __future__ import annotations

EXEC_ENABLED = False


def capabilities() -> dict[str, bool]:
    """What the UI may show. Phase 1: no command execution."""
    return {"exec": EXEC_ENABLED, "targets": False}
