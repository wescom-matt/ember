"""Decide whether a command may run without asking.

Fail closed: anything not clearly read-only or home-scoped needs a click on
Confirm. Unknown commands, unparseable input, command substitution, and
anything dangerous (deleting recursively, formatting, power, privilege,
package installs, flashing, writes outside home) are 'risky'.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from ember import config

SAFE = "safe"
RISKY = "risky"
MAX_SEGMENTS = 20
MAX_TOKENS = 400

LINUX_KNOWN = frozenset(
    [
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        "egrep",
        "fgrep",
        "rg",
        "find",
        "df",
        "du",
        "free",
        "uptime",
        "uname",
        "whoami",
        "id",
        "hostname",
        "ps",
        "pgrep",
        "top",
        "echo",
        "printf",
        "pwd",
        "date",
        "cal",
        "ip",
        "ifconfig",
        "ss",
        "netstat",
        "ping",
        "lsusb",
        "lsblk",
        "lscpu",
        "lspci",
        "dmesg",
        "journalctl",
        "which",
        "whereis",
        "type",
        "file",
        "stat",
        "wc",
        "sort",
        "uniq",
        "cut",
        "awk",
        "sed",
        "tr",
        "diff",
        "cmp",
        "md5sum",
        "sha256sum",
        "tree",
        "mkdir",
        "touch",
        "cp",
        "mv",
        "ln",
        "rm",
        "tee",
        "tar",
        "zip",
        "unzip",
        "gzip",
        "chmod",
        "chown",
        "gunzip",
        "git",
        "curl",
        "wget",
        "nvidia-smi",
        "sensors",
        "arduino-cli",
        "esptool",
        "esptool.py",
        "pio",
        "platformio",
        "python3",
        "python",
        "cd",
        "true",
        "test",
        "[",
        "basename",
        "dirname",
        "realpath",
        "readlink",
        "xxd",
        "hexdump",
        "od",
        "strings",
        "sleep",
        "seq",
        "nproc",
        "locale",
        "systemctl",
        "stty",
        "hostnamectl",
        "timedatectl",
        "ollama",
    ]
)
LINUX_RISKY = {
    "sudo": "uses sudo",
    "su": "switches user",
    "doas": "uses doas",
    "pkexec": "privilege escalation",
    "dd": "raw disk write (dd)",
    "shred": "destroys data",
    "wipefs": "wipes disks",
    "fdisk": "partitions disks",
    "parted": "partitions disks",
    "sfdisk": "partitions disks",
    "mount": "mounts filesystems",
    "umount": "unmounts filesystems",
    "shutdown": "power off/reboot",
    "reboot": "reboot",
    "poweroff": "power off",
    "halt": "power off",
    "init": "changes runlevel",
    "kill": "kills processes",
    "pkill": "kills processes",
    "killall": "kills processes",
    "crontab": "changes scheduled jobs",
    "apt": "package manager",
    "apt-get": "package manager",
    "dpkg": "package manager",
    "snap": "package manager",
    "dnf": "package manager",
    "yum": "package manager",
    "pacman": "package manager",
    "flatpak": "package manager",
    "pip": "installs packages",
    "pip3": "installs packages",
    "npm": "installs packages",
    "uv": "installs packages",
    "eval": "dynamic code",
    "exec": "replaces the shell",
    "source": "runs a script",
    ".": "runs a script",
    "bash": "runs a script",
    "sh": "runs a script",
    "zsh": "runs a script",
    "node": "runs a program",
    "ufw": "firewall change",
    "iptables": "firewall change",
    "chattr": "changes file attributes",
    "useradd": "user management",
    "userdel": "user management",
    "passwd": "password change",  # nosec B105
    "visudo": "sudo config",
    "xargs": "runs commands",
}
WIN_RISKY = {
    "format-volume": "formats a disk",
    "format-disk": "formats a disk",
    "clear-disk": "wipes a disk",
    "initialize-disk": "initializes a disk",
    "stop-computer": "power off",
    "restart-computer": "reboot",
    "shutdown": "power off/reboot",
    "set-executionpolicy": "changes script policy",
    "stop-process": "kills processes",
    "kill": "kills processes",
    "taskkill": "kills processes",
    "stop-service": "stops a service",
    "set-service": "changes a service",
    "new-service": "creates a service",
    "sc": "service control",
    "sc.exe": "service control",
    "reg": "registry change",
    "reg.exe": "registry change",
    "diskpart": "disk tool",
    "bcdedit": "boot config",
    "msiexec": "installs software",
    "winget": "installs software",
    "choco": "installs software",
    "install-module": "installs software",
    "install-package": "installs software",
    "invoke-expression": "dynamic code",
    "iex": "dynamic code",
    "set-itemproperty": "registry change",
    "new-itemproperty": "registry change",
    "netsh": "network config",
    "runas": "privilege escalation",
    "pip": "installs packages",
    "npm": "installs packages",
    "powershell": "runs a script",
    "pwsh": "runs a script",
    "cmd": "runs a script",
    "cmd.exe": "runs a script",
    "start-process": "starts a program",
}
WIN_KNOWN = frozenset(
    [
        "test-path",
        "test-connection",
        "select-object",
        "select-string",
        "where-object",
        "sort-object",
        "measure-object",
        "format-table",
        "format-list",
        "format-wide",
        "out-string",
        "write-output",
        "echo",
        "dir",
        "ls",
        "gci",
        "type",
        "cat",
        "gc",
        "ipconfig",
        "hostname",
        "whoami",
        "systeminfo",
        "tasklist",
        "where",
        "where.exe",
        "mode",
        "pwd",
        "cd",
        "set-location",
        "new-item",
        "copy-item",
        "move-item",
        "mkdir",
        "md",
        "esptool",
        "esptool.py",
        "arduino-cli",
        "pio",
        "python",
        "py",
        "ping",
        "nslookup",
        "remove-item",
        "rm",
        "del",
        "erase",
        "rd",
        "rmdir",
        "ri",
        "set-content",
        "add-content",
        "out-file",
    ]
)
WIN_DELETE = frozenset(["remove-item", "rm", "del", "erase", "rd", "rmdir", "ri"])
WIN_WRITE = frozenset(["set-content", "add-content", "out-file", "new-item", "copy-item", "move-item", "mkdir", "md"])
LINUX_WRITE = frozenset(["mkdir", "touch", "cp", "mv", "ln", "rm", "tee", "tar", "unzip"])


@dataclass
class Risk:
    level: str = SAFE
    reasons: list[str] = field(default_factory=list)

    def flag(self, reason: str) -> None:
        self.level = RISKY
        if reason not in self.reasons and len(self.reasons) < 10:
            self.reasons.append(reason)


def classify(command: str, os_type: str, home: str) -> Risk:
    risk = Risk()
    text = (command or "").strip()
    if not text:
        risk.flag("empty command")
        return risk
    if len(text) > config.MAX_COMMAND_CHARS:
        risk.flag("command too long")
        return risk
    if os_type == "windows":
        _classify_windows(text, home, risk)
    else:
        _classify_linux(text, home, risk)
    return risk


def _outside_home(path: str, home: str) -> bool:
    """True if a path (after ~ and $HOME expansion) points outside home and /tmp."""
    import posixpath

    p = path.replace("${HOME}", home).replace("$HOME", home)
    if p == "~" or p.startswith("~/"):
        p = home + p[1:]
    if "$" in p or p.startswith("~"):
        return True
    if p in ("/dev/null", "-"):
        return False
    full = posixpath.normpath(p if p.startswith("/") else posixpath.join(home, p))
    inside = [full == base or full.startswith(base.rstrip("/") + "/") for base in (home, "/tmp")]  # noqa: S108 # nosec B108
    return not any(inside)


def _linux_segments(text: str) -> tuple[list[list[str]], list[str]]:
    """Split into command segments and collect redirect targets. Raises ValueError if unparseable."""
    lexer = shlex.shlex(text.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    tokens = list(lexer)
    if len(tokens) > MAX_TOKENS:
        raise ValueError("too many tokens")
    segments: list[list[str]] = [[]]
    redirects: list[str] = []
    expect_target = False
    for tok in tokens:
        if expect_target:
            redirects.append(tok)
            expect_target = False
        elif tok in (">", ">>", "&>", ">|", "&>>"):
            expect_target = True
        elif tok in (">&", "<", "<<", "<<<"):
            continue
        elif tok and set(tok) <= set(";&|()"):
            segments.append([])
        else:
            segments[-1].append(tok)
    if expect_target:
        raise ValueError("dangling redirect")
    out = [s for s in segments if s]
    if len(out) > MAX_SEGMENTS:
        raise ValueError("too many commands")
    return out, redirects


def _classify_linux(text: str, home: str, risk: Risk) -> None:
    for marker in ("$(", "`", "<(", ">("):
        if marker in text:
            risk.flag("command substitution")
            return
    try:
        segments, redirects = _linux_segments(text)
    except ValueError:
        risk.flag("could not parse the command")
        return
    for target in redirects:
        if not target.isdigit() and _outside_home(target, home):
            risk.flag(f"writes outside home ({target})")
    for seg in segments:
        _linux_segment(seg, home, risk)


def _linux_segment(seg: list[str], home: str, risk: Risk) -> None:
    words = list(seg)
    for _ in range(len(seg)):
        if words and "=" in words[0] and not words[0].startswith("-") and words[0].split("=", 1)[0].isidentifier():
            words.pop(0)
        else:
            break
    if not words:
        return
    cmd = words[0].rsplit("/", 1)[-1]
    args = words[1:]
    if cmd == "command":
        if args[:1] not in (["-v"], ["-V"]):
            risk.flag("'command' can bypass checks")
        return
    if cmd in LINUX_RISKY:
        if cmd in ("pip", "pip3", "uv", "npm") and args[:1] in (["list"], ["show"], ["freeze"], ["--version"]):
            return
        risk.flag(LINUX_RISKY[cmd])
        return
    if cmd not in LINUX_KNOWN:
        risk.flag(f"unknown command '{cmd[:40]}'")
        return
    _linux_args(cmd, args, home, risk)


def _has_flag(args: list[str], short: str, longs: tuple[str, ...]) -> bool:
    for a in args:
        if a in longs:
            return True
        if a.startswith("-") and not a.startswith("--") and short in a[1:]:
            return True
    return False


def _linux_args(cmd: str, args: list[str], home: str, risk: Risk) -> None:
    low = [a.lower() for a in args]
    if cmd == "rm" and _has_flag(args, "r", ("--recursive",)) or cmd == "rm" and _has_flag(args, "R", ()):
        risk.flag("recursive delete (rm -r)")
    if cmd in ("chmod", "chown") and _has_flag(args, "R", ("--recursive",)):
        risk.flag(f"recursive {cmd}")
    if cmd == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir") for a in args):
        risk.flag("find with -delete/-exec")
    if cmd == "sed" and _has_flag(args, "i", ("--in-place",)):
        _check_paths(args, home, risk, "edits a file outside home")
    if cmd in LINUX_WRITE or cmd in ("chmod", "chown"):
        _check_paths(args, home, risk, "writes outside home")
    if cmd == "systemctl" and (not low or low[0] not in ("status", "is-active", "is-enabled", "list-units", "show")):
        risk.flag("changes a service")
    if cmd in ("esptool", "esptool.py") and any(
        a.replace("-", "_") in ("write_flash", "erase_flash", "erase_region", "burn_efuse", "write_mem") for a in low
    ):
        risk.flag("flashes a device (esptool)")
    if cmd == "arduino-cli" and any(a in ("upload", "burn-bootloader", "install", "uninstall", "upgrade") for a in low):
        risk.flag("uploads firmware or installs packages (arduino-cli)")
    if cmd in ("pio", "platformio") and _pio_risky(low):
        risk.flag("uploads firmware or installs packages (platformio)")
    if cmd in ("python", "python3") and low not in (["--version"], ["-v"], ["-V".lower()]):
        risk.flag("runs a program")
    if cmd == "git" and _git_risky(low):
        risk.flag("destructive git operation")
    if cmd == "ollama" and low[:1] in (["rm"], ["pull"], ["push"], ["cp"], ["create"]):
        risk.flag("changes Ollama models")


def _check_paths(args: list[str], home: str, risk: Risk, reason: str) -> None:
    for a in args:
        if a.startswith("-"):
            continue
        if _outside_home(a, home):
            risk.flag(f"{reason} ({a[:80]})")


def _pio_risky(low: list[str]) -> bool:
    if any(a in ("upload", "uploadfs", "program", "erase") for a in low):
        return True
    return bool(low[:1] in (["pkg"], ["upgrade"], ["update"], ["system"]) and "list" not in low)


def _git_risky(low: list[str]) -> bool:
    if not low:
        return False
    if low[0] in ("clean", "push"):
        return True
    return low[0] == "reset" and "--hard" in low


def _classify_windows(text: str, home: str, risk: Risk) -> None:
    lowered = text.lower()
    for marker in ("-encodedcommand", "-enc ", "$(", "[scriptblock]", "downloadstring", "invoke-webrequest", "iwr "):
        if marker in lowered:
            risk.flag("dynamic or downloaded code")
    try:
        lexer = shlex.shlex(text.replace("\n", " ; "), posix=False, punctuation_chars=";|&")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        risk.flag("could not parse the command")
        return
    segments: list[list[str]] = [[]]
    for tok in tokens[:MAX_TOKENS]:
        if tok and set(tok) <= set(";|&"):
            segments.append([])
        else:
            segments[-1].append(tok.strip("\"'"))
    for seg in segments[:MAX_SEGMENTS]:
        if seg:
            _windows_segment(seg, home, risk)


def _win_outside_home(path: str, home: str) -> bool:
    p = path.replace("/", "\\").lower()
    if p.startswith(("$env:", "$home")):
        p = p.replace("$env:userprofile", home.lower()).replace("$home", home.lower())
    if len(p) >= 2 and p[1] == ":" or p.startswith("\\\\"):
        return not p.startswith(home.lower().rstrip("\\") + "\\") and p != home.lower()
    return ".." in p


def _windows_segment(seg: list[str], home: str, risk: Risk) -> None:
    cmd = seg[0].lower()
    args = [a.lower() for a in seg[1:]]
    if cmd in WIN_RISKY:
        risk.flag(WIN_RISKY[cmd])
        return
    if cmd.startswith("get-") or cmd in WIN_KNOWN:
        if cmd in WIN_DELETE and any(a in ("-recurse", "-r", "/s", "/q", "-force") for a in args):
            risk.flag("recursive or forced delete")
        if cmd in WIN_DELETE or cmd in WIN_WRITE:
            for a in seg[1:]:
                if not a.startswith(("-", "/")) and _win_outside_home(a, home):
                    risk.flag(f"writes outside home ({a[:80]})")
        if cmd in ("python", "py") and args not in (["--version"], ["-v"]):
            risk.flag("runs a program")
        if cmd in ("esptool", "esptool.py", "arduino-cli", "pio") and _flash_args(args):
            risk.flag("flashes a device or installs packages")
        return
    risk.flag(f"unknown command '{cmd[:40]}'")


def _flash_args(args: list[str]) -> bool:
    flash = ("write_flash", "write-flash", "erase_flash", "erase-flash", "upload", "install", "uploadfs", "burn_efuse")
    return any(a in flash for a in args)
