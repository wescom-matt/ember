#!/usr/bin/env bash
# Sync the P1 project mirrors (~/git/*.git) with GitHub. Needs the key from
# scripts/p1-github-key.sh (or use scripts/windows/mirror-repos.ps1 from Los Gatos).
#   bash scripts/sync-mirrors.sh fetch   # GitHub -> P1 (fast-forward only; offline work is kept)
#   bash scripts/sync-mirrors.sh push    # P1 -> GitHub (branches and tags; never forced)
# A branch that moved on both sides is refused; merge it on a build host, push to p1, then push again.
set -euo pipefail
mode="${1:?usage: sync-mirrors.sh fetch|push}"
git_dir="${EMBER_GIT_DIR:-$HOME/git}"
for repo in "$git_dir"/*.git; do
  name="$(basename "$repo" .git)"
  url="github-mirrors:wescom-matt/$name.git"
  case "$mode" in
    fetch) git -C "$repo" fetch -q "$url" 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' \
             && echo "ok   $name" || echo "warn $name: some branches not fast-forward (kept the P1 copy)" ;;
    push)  git -C "$repo" push -q "$url" 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' \
             && echo "ok   $name" || echo "warn $name: GitHub has newer commits; fetch and merge first" ;;
    *) echo "usage: sync-mirrors.sh fetch|push"; exit 2 ;;
  esac
done
