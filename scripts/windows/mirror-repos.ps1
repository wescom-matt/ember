# Mirror every wescom-matt repo with this PC's GitHub login (HTTPS), save each repo's
# issues and pull requests as JSON, bundle everything and copy it to the P1, where import-mirrors.sh
# adds it to ~/git/*.git. Run in PowerShell as Matt (no admin):
#   powershell -ExecutionPolicy Bypass -File mirror-repos.ps1
# Needs: git, gh (logged in), OpenSSH client with a key the P1 accepts.
param(
  [string]$Dest = "$env:USERPROFILE\repo-mirrors",
  [string]$P1 = "matt@192.168.1.177"
)
$Repos = @('Outpost','ember','CamWall','FEW','FEW-Jenkins','BlackCat','bcfc-workspace',
           'SystemScrape','Face-AI','NomadHardware','rebuild-kit-builder','wescom')
New-Item -ItemType Directory -Force "$Dest\bundles" | Out-Null
foreach ($r in $Repos) {
  $m = "$Dest\$r.git"
  if (Test-Path $m) { git -C $m remote update --prune 2>&1 | Out-Null }
  else { git clone -q --mirror "https://github.com/wescom-matt/$r.git" $m 2>&1 | Out-Null }
  if ($LASTEXITCODE -ne 0) { Write-Warning "$r : fetch failed"; continue }
  git -C $m bundle create "$Dest\bundles\$r.bundle" --all 2>&1 | Out-Null
  Write-Output ("{0,-20} {1}" -f $r, (git -C $m log -1 --format='%h %cs' HEAD))
  # Issues and pull requests are not in git: save them as JSON for offline reading.
  gh issue list -R "wescom-matt/$r" --state all --limit 500 `
    --json number,title,state,labels,body,comments,createdAt,updatedAt,url |
    Set-Content -Encoding utf8 "$Dest\bundles\$r-issues.json"
  gh pr list -R "wescom-matt/$r" --state all --limit 500 `
    --json number,title,state,body,headRefName,baseRefName,createdAt,updatedAt,url |
    Set-Content -Encoding utf8 "$Dest\bundles\$r-prs.json"
}
ssh -o BatchMode=yes $P1 'rm -rf /tmp/repo-bundles; mkdir -p /tmp/repo-bundles'
scp -q @((Get-ChildItem "$Dest\bundles").FullName) "${P1}:/tmp/repo-bundles/"
ssh -o BatchMode=yes $P1 'bash ~/ember/scripts/import-mirrors.sh /tmp/repo-bundles'
