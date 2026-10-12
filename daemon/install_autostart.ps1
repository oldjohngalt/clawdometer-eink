# Register (or remove) a Task Scheduler task that starts the daemon at logon.
# Runs windowless (pythonw.exe); logs go to %USERPROFILE%\.clawd\daemon.log.
# Usage:  .\install_autostart.ps1            install / update
#         .\install_autostart.ps1 -Remove    uninstall
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$name = 'Clawdometer daemon'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Removed '$name'."
    return
}

$pyw = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
$script = Join-Path $PSScriptRoot 'claude_usage_daemon.py'
if (-not (Test-Path $pyw)) { throw "Missing $pyw - create the venv first (see WINDOWS.md)." }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "`"$script`" --plain" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
# Restart if it crashes; never time out; keep running on battery.
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Pushes Claude usage to the Clawdometer e-ink display over BLE.' -Force | Out-Null
Write-Host "Registered '$name'. Start it now with:  Start-ScheduledTask -TaskName '$name'"
