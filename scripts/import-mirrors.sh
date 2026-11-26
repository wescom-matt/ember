#!/usr/bin/env bash
# Add or refresh the project mirrors in ~/git/*.git from a folder of git bundles
# (made by scripts/windows/mirror-repos.ps1 or `coldboot.sh cache`).
#   bash scripts/import-mirrors.sh /tmp/repo-bundles
# Never overwrites offline work: branch updates that are not fast-forward are
# refused (git prints "rejected") and nothing is deleted.
set -euo pipefail
src="${1:?usage: import-mirrors.sh BUNDLE_DIR}"
git_dir="${EMBER_GIT_DIR:-$HOME/git}"
install -d "$git_dir/issues"
for b in "$src"/*.bundle; do
  [[ -f "$b" ]] || continue
  name="$(basename "$b" .bundle)"
  repo="$git_dir/$name.git"
  git bundle list-heads "$b" >/dev/null 2>&1 || { echo "skip $name: bad bundle"; continue; }
  if [[ ! -d "$repo" ]]; then
    git init -q --bare "$repo"
    git -C "$repo" remote add origin "https://github.com/wescom-matt/$name.git"
    echo "new  $name"
  fi
  git -C "$repo" fetch -q "$b" 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' || echo "warn $name: some branches not updated (offline work kept)"
  head="$(git -C "$repo" for-each-ref --format='%(refname:short)' refs/heads/main refs/heads/master | head -n 1)"
  [[ -n "$head" ]] && git -C "$repo" symbolic-ref HEAD "refs/heads/$head"
  echo "ok   $name $(git -C "$repo" log -1 --format='%h %cs' HEAD 2>/dev/null || echo empty)"
done
for j in "$src"/*-issues.json "$src"/*-prs.json "$src"/issues/*.json; do [[ -f "$j" ]] && cp "$j" "$git_dir/issues/"; done
echo "mirrors in $git_dir: $(find "$git_dir" -maxdepth 1 -name '*.git' | wc -l)"
