# Flash Clawdometer over USB on Windows. Finds the board's COM port automatically.
# Usage:  .\flash.ps1            (auto-detect)
#         .\flash.ps1 -Port COM5 (explicit)
param([string]$Port)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$pio = (Get-Command pio -ErrorAction SilentlyContinue).Source
if (-not $pio) { $pio = "$env:USERPROFILE\.platformio-venv\Scripts\pio.exe" }
if (-not (Test-Path $pio)) { throw "PlatformIO not found. Install it: pip install platformio" }

if (-not $Port) {
    # Espressif's native USB (VID 303A) only; Windows also lists Bluetooth serial ports.
    $dev = Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.PNPDeviceID -match 'VID_303A' -and $_.Name -match '\((COM\d+)\)' } |
        Select-Object -First 1
    if (-not $dev) {
        Write-Error "No board found. Plug the ESP32-S3 in with a USB *data* cable. If it still doesn't show, hold BOOT, tap RESET, release BOOT, and retry."
    }
    $Port = [regex]::Match($dev.Name, 'COM\d+').Value
}

Write-Host "Flashing via $Port"
& $pio run -t upload --upload-port $Port
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host ""
Write-Host "Done. Remember: restart the daemon now (the flash rebooted the device"
Write-Host "and dropped the BLE link)."
