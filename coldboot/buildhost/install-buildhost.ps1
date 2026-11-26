# Set up a Windows radio/build host (e.g. Los Gatos) for Ember. User level: no admin rights.
#
#   powershell -ExecutionPolicy Bypass -File install-buildhost.ps1 [-Cache E:\coldboot-cache] [-Radio] [-Build]
#
#   -Radio  CHIRP (chirpc) for radio cables   (needs Python 3.10+ from python.org, "py" launcher)
#   -Build  OrcaSlicer + ElegooSlicer (portable), Centauri Carbon 2 profiles, arduino-cli,
#           PlatformIO + esptool (needs Python)
#   (neither) both.  Everything goes under %USERPROFILE%\ember-tools and is checked against pins.txt.
# AnyTone AT-D868UV and Kenwood radios without a CHIRP driver still need the maker's CPS/KPG software.
param([string]$Cache = "", [switch]$Radio, [switch]$Build)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Pins = Join-Path $Here "..\pins.txt"
$Tools = Join-Path $env:USERPROFILE "ember-tools"
$BinDir = Join-Path $Tools "bin"
$Scratch = Join-Path $env:TEMP ("ember-buildhost-" + [guid]::NewGuid().ToString("N"))
if (-not ($Radio -or $Build)) { $Radio = $true; $Build = $true }
New-Item -ItemType Directory -Force $Tools, $BinDir, $Scratch | Out-Null

function Get-Pin([string]$Name) {
    foreach ($line in Get-Content $Pins) {
        $f = $line -split '\s+'
        if ($f[0] -eq $Name) { return @{ Sha = $f[1]; Rel = $f[2]; Url = $f[3] } }
    }
    throw "no pin named $Name"
}

function Get-Pinned([string]$Name) {
    $p = Get-Pin $Name
    if ($Cache -and (Test-Path (Join-Path $Cache $p.Rel))) { $file = Join-Path $Cache $p.Rel }
    else {
        $file = Join-Path $Scratch (Split-Path -Leaf $p.Rel)
        Write-Host "    downloading $($p.Url)"
        Invoke-WebRequest -UseBasicParsing -Uri $p.Url -OutFile $file
    }
    $sha = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
    if ($sha -ne $p.Sha) { throw "checksum mismatch for $Name" }
    return $file
}

function Expand-Pinned([string]$Name, [string]$Dest) {
    if (Test-Path $Dest) { Write-Host "    $Dest already there"; return }
    $zip = Get-Pinned $Name
    Expand-Archive -Path $zip -DestinationPath $Dest
    Write-Host "    unpacked $Name -> $Dest"
}

function New-ToolVenv([string]$Dir, [string]$Req, [string]$Wheels) {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if (-not $py) { Write-Warning "Python launcher 'py' not found: install Python 3.12 from python.org, then re-run"; return $false }
    if (-not (Test-Path "$Dir\Scripts\python.exe")) { & py -3 -m venv $Dir }
    # Windows: online install (the cache holds Linux wheels only). Versions follow the .in file.
    & "$Dir\Scripts\pip.exe" install -q -r $Req
    return ($LASTEXITCODE -eq 0)
}

function Set-Shim([string]$Name, [string]$Target) {
    Set-Content -Encoding ASCII -Path (Join-Path $BinDir "$Name.cmd") -Value "@`"$Target`" %*"
}

if ($Radio) {
    Write-Host "=== CHIRP (chirpc)"
    $venv = Join-Path $Tools "chirp-venv"
    if (New-ToolVenv $venv (Join-Path $Here "chirp-requirements.in") "") {
        $tar = Get-Pinned "chirp"
        & "$venv\Scripts\pip.exe" install -q --no-deps --no-build-isolation $tar
        Set-Shim "chirpc" "$venv\Scripts\chirpc.exe"
    }
}

if ($Build) {
    Write-Host "=== Slicers (portable) and Centauri Carbon 2 profiles"
    Expand-Pinned "orca-win" (Join-Path $Tools "OrcaSlicer")
    Expand-Pinned "elegoo-win" (Join-Path $Tools "ElegooSlicer")
    $prof = Join-Path $Tools "slicer-profiles\cc2"
    if ($Cache -and (Test-Path (Join-Path $Cache "slicers\cc2-profiles"))) {
        New-Item -ItemType Directory -Force $prof | Out-Null
        Copy-Item -Recurse -Force (Join-Path $Cache "slicers\cc2-profiles\*") $prof
    } elseif (-not (Test-Path "$prof\machine")) {
        & py -3 (Join-Path $Here "cc2_profiles.py") $prof
    }
    Write-Host "=== arduino-cli"
    Expand-Pinned "arduino-cli-win" (Join-Path $Tools "arduino-cli")
    Set-Shim "arduino-cli" (Join-Path $Tools "arduino-cli\arduino-cli.exe")
    Write-Host "=== PlatformIO + esptool"
    $pvenv = Join-Path $Tools "pio-venv"
    if (New-ToolVenv $pvenv (Join-Path $Here "pio-requirements.in") "") {
        Set-Shim "pio" "$pvenv\Scripts\pio.exe"
        Set-Shim "esptool" "$pvenv\Scripts\esptool.exe"
    }
    Write-Host "    note: ESP32 toolchains download the first time you build (the cache holds Linux ones only)"
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ';') -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$BinDir", "User")
    Write-Host "    added $BinDir to your PATH (open a new window)"
}
Remove-Item -Recurse -Force $Scratch
Write-Host "Done. Radio cables need the USB-serial driver (CH340/CP210x/FTDI) from the cable maker."
