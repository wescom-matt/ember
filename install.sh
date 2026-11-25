#!/usr/bin/env bash
# Ember installer (no sudo). Safe to re-run. ColdBoot (./coldboot.sh) calls this.
# EMBER_WHEELS=/dir installs from pre-downloaded wheels with no internet.
set -euo pipefail

EMBER_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export EMBER_HOME
CONF_DIR="$HOME/.config/ember"
TLS_DIR="$CONF_DIR/tls"
UNIT_DIR="$HOME/.config/systemd/user"
SUDO_NOTES="$HOME/ember-sudo-steps.sh"

say() { printf '==> %s\n' "$*"; }

find_uv() {
  if command -v uv >/dev/null 2>&1; then command -v uv; return 0; fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then echo "$HOME/.local/bin/uv"; return 0; fi
  echo "uv not found; install it first (see README)." >&2
  return 1
}

make_venv() {
  local uv
  uv="$(find_uv)"
  say "Python venv (3.12) and pinned packages"
  "$uv" venv -q --allow-existing --python 3.12 "$EMBER_HOME/.venv"
  local offline=()
  if [[ -n "${EMBER_WHEELS:-}" ]]; then offline=(--offline --no-index --find-links "$EMBER_WHEELS"); fi
  "$uv" pip install -q --python "$EMBER_HOME/.venv/bin/python" "${offline[@]}" --require-hashes -r "$EMBER_HOME/requirements.txt"
  if [[ "${EMBER_DEV:-0}" == "1" ]]; then
    "$uv" pip install -q --python "$EMBER_HOME/.venv/bin/python" --require-hashes -r "$EMBER_HOME/requirements-dev.txt"
  fi
}

write_config() {
  install -d -m 700 "$CONF_DIR" "$TLS_DIR" "$HOME/.local/share/ember"
  if [[ ! -f "$CONF_DIR/ember.env" ]]; then
    say "Config: $CONF_DIR/ember.env"
    install -m 600 "$EMBER_HOME/deploy/ember.env.example" "$CONF_DIR/ember.env"
  fi
}

make_cert() {
  if [[ -f "$TLS_DIR/ember.crt" && -f "$TLS_DIR/ember.key" ]]; then return 0; fi
  say "Self-signed TLS certificate (10 years) in $TLS_DIR"
  local ip
  ip="$(hostname -I | awk '{print $1}')"
  local san
  san="DNS:localhost,DNS:$(hostname),IP:127.0.0.1"
  if [[ -n "$ip" ]]; then san="$san,IP:$ip"; fi
  ( umask 077
    openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
      -keyout "$TLS_DIR/ember.key" -out "$TLS_DIR/ember.crt" \
      -subj "/CN=ember" -addext "subjectAltName=$san" 2>/dev/null )
  chmod 600 "$TLS_DIR/ember.key"
}

install_unit() {
  say "systemd --user unit and 'ember' helper"
  install -d "$UNIT_DIR" "$HOME/.local/bin"
  install -m 644 "$EMBER_HOME/deploy/ember.service" "$UNIT_DIR/ember.service"
  ln -sfn "$EMBER_HOME/bin/ember" "$HOME/.local/bin/ember"
  # systemd does not expand %h inside EnvironmentFile values; write real paths.
  sed -i "s|%h|$HOME|g" "$CONF_DIR/ember.env"
  systemctl --user daemon-reload
  systemctl --user enable ember.service >/dev/null
  systemctl --user restart ember.service
}

check_linger() {
  if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo no)" == "yes" ]]; then return 0; fi
  if loginctl enable-linger "$USER" 2>/dev/null; then say "Linger on: Ember runs without anyone logged in"; return 0; fi
  say "Linger needs sudo once; see $SUDO_NOTES"
  printf '#!/usr/bin/env bash\nset -euo pipefail\n# Keep Ember (a user service) running after logout and at boot.\nsudo loginctl enable-linger %s\n' \
    "$USER" > "$SUDO_NOTES"
  chmod 700 "$SUDO_NOTES"
}

main() {
  make_venv
  write_config
  make_cert
  install_unit
  check_linger
  sleep 2
  systemctl --user --no-pager --lines=0 status ember.service | head -n 3 || true
  local url
  url="$("$EMBER_HOME/bin/ember" url)"
  say "Done. Create your admin: ember create-admin <name>   Then open: $url"
}

main "$@"
