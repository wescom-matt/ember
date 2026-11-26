# Restore every .NET solution in the project mirrors into one local NuGet folder,
# pack it and copy it to the P1 (~/offline/nuget.tar.gz), where `coldboot.sh cache`
# picks it up. Run in PowerShell as Matt (no admin), after mirror-repos.ps1:
#   powershell -ExecutionPolicy Bypass -File nuget-offline.ps1
# Offline use on a build host: unpack it, then
#   dotnet restore --source C:\offline-nuget   (or add that folder as a package source)
param(
  [string]$Mirrors = "$env:USERPROFILE\repo-mirrors",
  [string]$Out = "$env:USERPROFILE\offline-nuget",
  [string]$P1 = "matt@192.168.1.177"
)
$Repos = @('CamWall','FEW','BlackCat','bcfc-workspace','SystemScrape')
$src = Join-Path $env:TEMP "nuget-src"
Remove-Item -Recurse -Force $src -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $src, $Out | Out-Null
foreach ($r in $Repos) {
  git clone -q "$Mirrors\$r.git" "$src\$r" 2>&1 | Out-Null
  $slns = @(Get-ChildItem "$src\$r" -Recurse -Filter *.sln -File)
  if ($slns.Count -eq 0) { $slns = @(Get-ChildItem "$src\$r" -Recurse -Filter *.csproj -File) }
  foreach ($s in $slns) {
    dotnet restore $s.FullName --packages $Out --verbosity quiet 2>&1 | Out-Null
    $ok = if ($LASTEXITCODE -eq 0) { "ok  " } else { "FAIL" }
    Write-Output "$ok $r\$($s.Name)"
  }
}
Remove-Item -Recurse -Force $src -ErrorAction SilentlyContinue
$tgz = Join-Path $env:TEMP "nuget.tar.gz"
tar -czf $tgz -C $Out .
Write-Output ("packages: {0}  tarball: {1:N0} MB" -f (Get-ChildItem $Out -Directory).Count, ((Get-Item $tgz).Length / 1MB))
ssh -o BatchMode=yes $P1 'mkdir -p ~/offline'
scp -q $tgz "${P1}:offline/nuget.tar.gz"
Remove-Item $tgz
