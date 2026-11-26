# Los Gatos steps as Matt (NO admin), while online. Safe to repeat.
#   powershell -ExecutionPolicy Bypass -File los-gatos-user-steps.ps1
# 1. Fetch all existing clones (fast-forward only if clean) and add the 'p1' remote.
# 2. Clone the 3 repos that are missing here.
# 3. One online Outpost Android build, which fills the Gradle cache for offline builds.
$P1 = "matt@192.168.1.177"
$clones = @{
  'Outpost' = "$env:USERPROFILE\Documents\Outpost"; 'CamWall' = "$env:USERPROFILE\bin\sidestep\camwall"
  'SystemScrape' = "$env:USERPROFILE\bin\sidestep\system_scrape"; 'Face-AI' = "$env:USERPROFILE\Face_AI"
  'FEW' = "$env:USERPROFILE\FEW"; 'FEW-Jenkins' = "$env:USERPROFILE\FEW-Jenkins"; 'NomadHardware' = "$env:USERPROFILE\NomadHardware"
  'BlackCat' = "$env:USERPROFILE\BlackCat"; 'bcfc-workspace' = "$env:USERPROFILE\bcfc-workspace"
  'rebuild-kit-builder' = "$env:USERPROFILE\rebuild-kit-builder"
}
Write-Output "== 1-2. Clones"
foreach ($name in $clones.Keys) {
  $dir = $clones[$name]
  if (-not (Test-Path "$dir\.git")) { git clone -q "https://github.com/wescom-matt/$name.git" $dir; Write-Output "cloned  $name" }
  git -C $dir fetch -q --all --prune
  if (-not (git -C $dir status --porcelain)) { git -C $dir pull -q --ff-only 2>$null }
  if (-not (git -C $dir remote | Select-String -SimpleMatch 'p1')) { git -C $dir remote add p1 "${P1}:git/$name.git" }
  Write-Output ("{0,-20} {1}" -f $name, (git -C $dir log -1 --format='%h %cs %s'))
}
Write-Output "== 3. Outpost Android build (online once; fills ~/.gradle, ~1.5-2 GB)"
Push-Location "$env:USERPROFILE\Documents\Outpost"
flutter precache --android
flutter pub get
& "$env:ProgramFiles\Git\bin\bash.exe" scripts/pre_build_assets.sh android
flutter build apk --release --target-platform android-arm64
Pop-Location
Write-Output "Done. Gradle and pub now have what an offline Outpost Android build needs."
