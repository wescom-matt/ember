#!/usr/bin/env bash
# OPTIONAL, run by Matt on the P1: give the P1 its own GitHub key so it can refresh the
# project mirrors (scripts/sync-mirrors.sh) without Los Gatos. Prints the PUBLIC key only.
#   bash scripts/p1-github-key.sh
# Then add the printed key at https://github.com/settings/keys (New SSH key, title "P1 mirrors").
set -euo pipefail
key="$HOME/.ssh/github_mirrors"
install -d -m 700 "$HOME/.ssh"
if [[ ! -f "$key" ]]; then
  ssh-keygen -q -t ed25519 -N "" -C "p1-mirrors@$(hostname)" -f "$key"
fi
if ! grep -q "Host github-mirrors" "$HOME/.ssh/config" 2>/dev/null; then
  printf '\nHost github-mirrors\n  HostName github.com\n  User git\n  IdentityFile %s\n  IdentitiesOnly yes\n' "$key" >> "$HOME/.ssh/config"
  chmod 600 "$HOME/.ssh/config"
fi
echo "Add this PUBLIC key to GitHub (https://github.com/settings/keys):"
cat "$key.pub"
echo "Test afterwards: ssh -T github-mirrors   (should greet wescom-matt)"
