# Los Gatos steps that need an ADMIN PowerShell (Matt runs these by hand; Ember never does).
#   Right-click PowerShell > Run as administrator, then:
#   powershell -ExecutionPolicy Bypass -File los-gatos-admin-steps.ps1 [-EmberPublicKey "ssh-ed25519 AAAA... ember"]
# 1. OpenSSH Server so Ember can use Los Gatos as a build/radio host (home network only).
# 2. CMake + a C++ compiler (MinGW-w64 GCC) for Outpost's native tests.
# 3. Checks for Inno Setup (CamWall/FEW installers) and offers to install it.
param([string]$EmberPublicKey = "")

Write-Output "== 1. OpenSSH Server"
$cap = Get-WindowsCapability -Online -Name OpenSSH.Server*
if ($cap.State -ne 'Installed') { Add-WindowsCapability -Online -Name $cap.Name | Out-Null }
Set-Service sshd -StartupType Automatic
Start-Service sshd
# Allow only the home network (Private profile), not public Wi-Fi.
if (-not (Get-NetFirewallRule -Name 'Ember-SSH-LAN' -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -Name 'Ember-SSH-LAN' -DisplayName 'OpenSSH (home LAN only)' -Enabled True `
    -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -Profile Private | Out-Null
}
# PowerShell as the SSH shell (Ember sends PowerShell commands to Windows hosts).
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
  -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' -PropertyType String -Force | Out-Null
if ($EmberPublicKey) {
  # Matt is an administrator, so Windows reads administrators_authorized_keys.
  $f = 'C:\ProgramData\ssh\administrators_authorized_keys'
  Add-Content -Path $f -Value $EmberPublicKey
  icacls $f /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
  Write-Output "Ember key added to $f"
}
Get-Service sshd | Format-Table Name, Status, StartType -AutoSize

Write-Output "== 2. CMake + GCC for Outpost native tests"
winget install -e --id Kitware.CMake --accept-package-agreements --accept-source-agreements
winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT --accept-package-agreements --accept-source-agreements
Write-Output "Open a NEW terminal, then check:  cmake --version ; g++ --version"

Write-Output "== 3. Inno Setup (installers)"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) { Write-Output "Inno Setup found: $iscc" }
else {
  Write-Output "Inno Setup not found."
  if ((Read-Host "Install it now with winget? (y/n)") -eq 'y') {
    winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
  }
}
