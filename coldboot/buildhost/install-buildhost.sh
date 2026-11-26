#!/usr/bin/env bash
# Set up a Linux radio host and/or build host for Ember. User level only: no sudo.
# Steps that need sudo are written to ~/buildhost-sudo-steps.sh for you to read and run.
#
#   bash install-buildhost.sh [--cache DIR] [--radio] [--build] [--chirp-only] [--dry-run]
#
#   --radio       CHIRP (chirpc) for programming radios over a USB cable
#   --build       PlatformIO, esptool, arduino-cli (+ESP32 core, LoRa libraries), OrcaSlicer,
#                 ElegooSlicer and Centauri Carbon 2 profiles
#   (neither)     both
#   --chirp-only  just the CHIRP venv (used on the P1 for Ember's radio helper)
#   --cache DIR   use a ColdBoot cache (USB) instead of the internet
# Every download is checked against coldboot/pins.txt or a hashed requirements file.
set -euo pipefail
umask 022

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PINS="$HERE/../pins.txt"
CACHE=""
DRY=0
WANT_RADIO=0
WANT_BUILD=0
CHIRP_ONLY=0
SHARE="$HOME/.local/share/ember"
OPT="$HOME/.local/opt"
BIN="$HOME/.local/bin"
SUDO_FILE="$HOME/buildhost-sudo-steps.sh"
SCRATCH="$(mktemp -d -t buildhost.XXXXXX)"
trap 'rm -rf "$SCRATCH"' EXIT

say()  { printf '\n=== %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf 'install-buildhost: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
sha_of() { sha256sum "$1" | cut -c1-64; }
pin_field() { awk -v n="$1" -v f="$2" '$1 == n { print $f; exit }' "$PINS"; }
act() {
  local what="$1"; shift
  if [[ "$DRY" == "1" ]]; then info "[dry-run] $what"; return 0; fi
  info "$what"
  "$@"
}

# get_pinned NAME -> verified file path (cache first, then https download)
get_pinned() {
  local rel sha url dest
  rel="$(pin_field "$1" 3)"; sha="$(pin_field "$1" 2)"; url="$(pin_field "$1" 4)"
  [[ -n "$rel" ]] || die "no pin named $1"
  if [[ -n "$CACHE" && -f "$CACHE/$rel" ]]; then
    [[ "$(sha_of "$CACHE/$rel")" == "$sha" ]] || die "checksum mismatch: $CACHE/$rel"
    echo "$CACHE/$rel"; return 0
  fi
  [[ -n "$url" && "$url" != "-" ]] || die "$1 not in cache and no download URL"
  dest="$SCRATCH/$(basename "$rel")"
  curl -fsSL --proto '=https' --tlsv1.2 --max-time 3600 -o "$dest" "$url" >&2 || die "download failed: $url"
  [[ "$(sha_of "$dest")" == "$sha" ]] || die "checksum mismatch for $url"
  echo "$dest"
}

python_bin() {
  local p
  for p in python3.12 python3.13 python3.11 python3.10 python3; do
    if have "$p" && "$p" -c 'import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
      command -v "$p"; return 0
    fi
  done
  return 1
}

# make_venv DIR REQFILE WHEELDIR
make_venv() {
  local dir="$1" req="$2" wheels="$3" py
  local uv="${UV:-$HOME/.local/bin/uv}"
  if py="$(python_bin)"; then
    act "create venv $dir" "$py" -m venv "$dir"
  elif [[ -x "$uv" ]]; then
    # no system venv module: use uv's own Python 3.12 (user-level, no sudo)
    act "create venv $dir (uv)" "$uv" venv -q --seed --python 3.12 "$dir"
  else
    SUDO_NEED+=("sudo apt install -y python3-venv python3-pip"); info "python3 venv missing (see sudo steps)"; return 1
  fi
  if [[ -n "$CACHE" && -d "$wheels" ]]; then
    act "install $(basename "$req") from cache" "$dir/bin/pip" install -q --no-index --find-links "$wheels" --require-hashes -r "$req"
  else
    act "install $(basename "$req")" "$dir/bin/pip" install -q --require-hashes -r "$req"
  fi
}

link() { act "link $2 -> $1" ln -sfn "$1" "$BIN/$2"; }

step_chirp() {
  say "CHIRP (chirpc) in $SHARE/chirp-venv"
  local tar
  if [[ -x "$SHARE/chirp-venv/bin/chirpc" ]]; then info "already installed"; link "$SHARE/chirp-venv/bin/chirpc" chirpc; return 0; fi
  tar="$(get_pinned chirp)"
  make_venv "$SHARE/chirp-venv" "$HERE/chirp-requirements.txt" "$CACHE/chirp/wheels" || return 0
  act "install CHIRP $(basename "$tar")" "$SHARE/chirp-venv/bin/pip" install -q --no-deps --no-build-isolation "$tar"
  link "$SHARE/chirp-venv/bin/chirpc" chirpc
  SUDO_NEED+=("sudo usermod -aG dialout $USER   # serial port access for radio cables (log out and back in)")
}

step_pio() {
  say "PlatformIO + esptool in $SHARE/pio-venv"
  if [[ ! -x "$SHARE/pio-venv/bin/pio" ]]; then
    make_venv "$SHARE/pio-venv" "$HERE/pio-requirements.txt" "$CACHE/buildhost/pio-wheels" || return 0
  fi
  local b
  for b in pio platformio esptool esptool.py; do
    if [[ -e "$SHARE/pio-venv/bin/$b" ]]; then link "$SHARE/pio-venv/bin/$b" "$b"; fi
  done
  if [[ -n "$CACHE" && -d "$CACHE/buildhost/platformio" ]]; then
    act "copy cached PlatformIO packages (ESP32 toolchains, LoRa libraries) to ~/.platformio" \
      cp -rn "$CACHE/buildhost/platformio/." "$HOME/.platformio/"
  fi
  local rules
  rules="$(get_pinned pio-udev)"
  act "keep PlatformIO udev rules in $SHARE" install -D -m 644 "$rules" "$SHARE/99-platformio-udev.rules"
  SUDO_NEED+=("sudo install -m 644 $SHARE/99-platformio-udev.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules")
}

step_arduino() {
  say "arduino-cli (+ ESP32 core and LoRa libraries from the cache)"
  local tgz
  tgz="$(get_pinned arduino-cli-linux)"
  act "unpack arduino-cli to $BIN" tar -xzf "$tgz" -C "$BIN" arduino-cli
  if [[ -n "$CACHE" && -d "$CACHE/buildhost/arduino15" ]]; then
    act "copy cached Arduino data (esp32 core) to ~/.arduino15" cp -rn "$CACHE/buildhost/arduino15/." "$HOME/.arduino15/"
    act "copy cached Arduino libraries to ~/Arduino" cp -rn "$CACHE/buildhost/Arduino/." "$HOME/Arduino/"
  else
    info "no cache: run later (online):"
    info "  arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json"
    info "  arduino-cli core install esp32:esp32 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json"
  fi
}

# install_appimage PIN NAME LINK
install_appimage() {
  local img dest="$OPT/$2"
  if [[ -x "$dest/AppRun" ]]; then info "$2 already unpacked"; link "$dest/AppRun" "$3"; return 0; fi
  img="$(get_pinned "$1")"
  if [[ "$DRY" == "1" ]]; then info "[dry-run] unpack $img -> $dest"; return 0; fi
  cp "$img" "$SCRATCH/app.AppImage" && chmod 755 "$SCRATCH/app.AppImage"
  (cd "$SCRATCH" && ./app.AppImage --appimage-extract >/dev/null)
  mkdir -p "$OPT" && rm -rf "$dest" && mv "$SCRATCH/squashfs-root" "$dest"
  info "unpacked $2 (no FUSE needed)"
  link "$dest/AppRun" "$3"
}

step_slicers() {
  say "Slicers: OrcaSlicer (CLI used by Ember) and ElegooSlicer, plus Centauri Carbon 2 profiles"
  install_appimage orca-linux OrcaSlicer-2.5.2 orca-slicer
  install_appimage elegoo-linux ElegooSlicer-1.5.3.5 elegoo-slicer
  local prof="$SHARE/slicer-profiles/cc2"
  if [[ -n "$CACHE" && -d "$CACHE/slicers/cc2-profiles" ]]; then
    act "copy CC2 profiles" mkdir -p "$prof"
    act "  ..." cp -r "$CACHE/slicers/cc2-profiles/." "$prof/"
  elif [[ ! -d "$prof/machine" ]]; then
    act "build CC2 profiles from OrcaSlicer source (internet)" python3 "$HERE/cc2_profiles.py" "$prof"
  fi
  SUDO_NEED+=("sudo apt install -y libwebkit2gtk-4.1-0 libegl1 libgl1   # OrcaSlicer/ElegooSlicer runtime")
}

write_sudo() {
  [[ ${#SUDO_NEED[@]} -gt 0 ]] || return 0
  local out="$SCRATCH/sudo.sh" line
  {
    echo "#!/usr/bin/env bash"
    echo "# Ember build/radio host steps that need sudo. Read each line; run with: bash $SUDO_FILE"
    echo "set -euo pipefail"
    for line in "${SUDO_NEED[@]}"; do echo "$line"; done
  } > "$out"
  if [[ "$DRY" == "1" ]]; then say "Sudo steps (dry-run)"; cat "$out"; return 0; fi
  install -m 700 "$out" "$SUDO_FILE"
  say "Sudo steps written to $SUDO_FILE"
  cat "$SUDO_FILE"
}

main() {
  SUDO_NEED=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --cache) CACHE="$(cd "${2:?--cache needs a dir}" && pwd)"; shift 2 ;;
      --radio) WANT_RADIO=1; shift ;;
      --build) WANT_BUILD=1; shift ;;
      --chirp-only) CHIRP_ONLY=1; shift ;;
      --dry-run) DRY=1; shift ;;
      -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
      *) die "unknown option $1" ;;
    esac
  done
  if [[ "$WANT_RADIO$WANT_BUILD" == "00" ]]; then WANT_RADIO=1; WANT_BUILD=1; fi
  [[ "$DRY" == "1" ]] || mkdir -p "$BIN" "$SHARE"
  case ":$PATH:" in *":$BIN:"*) ;; *) info "note: add $BIN to PATH (new terminal usually does it)";; esac
  if [[ "$CHIRP_ONLY" == "1" ]]; then step_chirp; SUDO_NEED=(); say "Done (CHIRP only)"; return 0; fi
  if [[ "$WANT_RADIO" == "1" ]]; then step_chirp; fi
  if [[ "$WANT_BUILD" == "1" ]]; then step_pio; step_arduino; step_slicers; fi
  write_sudo
  say "Done. Check: chirpc --help | head -1 ; pio --version ; arduino-cli version ; orca-slicer --help | head -1"
}

main "$@"
