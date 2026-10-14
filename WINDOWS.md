# Clawdometer on Windows

Tested on Windows 11 with Python 3.14 and a Waveshare ESP32-S3-ePaper-1.54. The
firmware is unchanged (it still says "waiting for Mac..." until the first push —
cosmetic).

## 1. Firmware

```powershell
python -m venv $HOME\.platformio-venv
& $HOME\.platformio-venv\Scripts\python.exe -m pip install platformio intelhex
cd firmware
& $HOME\.platformio-venv\Scripts\pio.exe run      # compile
.\flash.ps1                                         # auto-finds the COM port (Espressif VID 303A)
```

`intelhex` is needed because PlatformIO's bundled esptool imports it but doesn't
install it (`ModuleNotFoundError: intelhex` while building `bootloader.bin`).
If the board doesn't enumerate: use a data cable, or hold BOOT, tap RESET, release BOOT.
If PowerShell blocks the script: `powershell -ExecutionPolicy Bypass -File .\flash.ps1`.

## 2. Token

On Windows the desktop app doesn't keep `%USERPROFILE%\.claude\.credentials.json`
fresh, so its token expires. Use a long-lived token instead:

```powershell
claude setup-token                                  # browser login, prints the token
Read-Host "Paste token" | Set-Content -NoNewline "$HOME\.clawd\oauth_token"
```

The daemon reads, in order: `CLAUDE_CODE_OAUTH_TOKEN` env var, `~\.clawd\oauth_token`,
then `~\.claude\.credentials.json`. Never commit the token.

## 3. Daemon

```powershell
cd daemon
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python.exe claude_usage_daemon.py           # live dashboard
.\.venv\Scripts\python.exe claude_usage_daemon.py --plain   # line logs
```

Bluetooth must be on. Don't pair the board in Windows Settings; the daemon
connects directly. Its address is cached in `~\.config\claude-usage-monitor\ble-address`.
Restart the daemon after every flash.

Autostart at logon (windowless, logs to `~\.clawd\daemon.log`):

```powershell
.\install_autostart.ps1            # install
.\install_autostart.ps1 -Remove    # uninstall
```

Options go in `%USERPROFILE%\.config\claude-usage-monitor\config`, one `key=value`
per line, re-read every poll (no restart needed):

```
volume=75      # chime volume 0-100 (0 silent, 50 = upstream default, 100 = max); device plays a preview on change
idle_sleep=15  # minutes of Claude Code inactivity before the device deep-sleeps (0 = stay linked)
chime=on       # session-reset chime
clock=auto     # show the time (auto|12|24|off)
```

## 4. Hooks

```powershell
mkdir $HOME\.clawd -Force; copy hooks\cc_status_hook.py $HOME\.clawd\
```

Merge into `%USERPROFILE%\.claude\settings.json` (Claude Code runs hooks via Git
Bash, so use forward slashes and quote the full interpreter path):

```json
{
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "\"C:/Users/<you>/AppData/Local/Microsoft/WindowsApps/python.exe\" \"C:/Users/<you>/.clawd/cc_status_hook.py\"" }] }],
    "PreToolUse": [{ "matcher": "*", "hooks": [{ "type": "command", "command": "<same command>" }] }],
    "Notification": [{ "hooks": [{ "type": "command", "command": "<same command>" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "<same command>" }] }]
  }
}
```

Restart open Claude Code sessions afterwards (hooks load at session start).

## Windows-specific changes

- `daemon/claude_usage_daemon.py`: long-lived token file / env var; UTF-8 transcript
  reads; ANSI enable for legacy consoles; 12/24h from the registry; log to file
  under `pythonw.exe`; connect via the scanned BLEDevice with a 45s timeout
  (WinRT connects take ~17s, and a bare address triggers a second scan — the
  original 20s limit made every reconnect fail).
- `hooks/cc_status_hook.py`: read stdin as UTF-8 (Windows defaults to cp1252; also
  strips the BOM PowerShell adds when piping).
- `firmware/flash.ps1`, `daemon/install_autostart.ps1`: new.
