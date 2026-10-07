"""Read-only Windows Up-arrow diagnostics. No input is blocked or generated."""
import argparse
import ctypes
import json
import math
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def summarize(events, initially_down=False):
    held = initially_down
    repeats = 0
    for event in events:
        if event["action"] == "down":
            repeats += int(held)
            held = True
        else:
            held = False
    result = {
        "down_events": sum(e["action"] == "down" for e in events),
        "up_events": sum(e["action"] == "up" for e in events),
        "injected_events": sum(e["injected"] for e in events),
        "repeated_down_without_release": repeats,
        "initially_down": initially_down,
        "last_event_state_down": held,
    }
    if not events:
        result["finding"] = "No Up-arrow events observed during this capture; this does not establish that the problem is absent."
    elif result["injected_events"]:
        result["finding"] = "Software-injected Up-arrow events observed. This flag does not identify the sending process; on-screen keyboards and remote-input tools can also set it."
    elif repeats and held:
        result["finding"] = "Repeated Up-arrow key-down events without a final release observed. Device, driver and unflagged input sources remain possible."
    elif repeats:
        result["finding"] = "Repeated key-down events observed, followed by release. Repeat is normal while a key is held; compare the event timing with when you physically released it."
    else:
        result["finding"] = "No continuous repeat captured. Compare the capture with a reproduction of the problem."
    return result


def monitor(seconds):
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    result_type = ctypes.c_ssize_t
    callback_type = ctypes.WINFUNCTYPE(result_type, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    class KeyboardEvent(ctypes.Structure):
        _fields_ = [("vkCode", wintypes.DWORD), ("scanCode", wintypes.DWORD),
                    ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_size_t)]

    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HANDLE
    user32.CallNextHookEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = result_type
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = result_type
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    events = []
    started = time.monotonic()
    initially_down = bool(user32.GetAsyncKeyState(0x26) & 0x8000)
    hook = None
    truncated = False

    @callback_type
    def callback(code, message, address):
        nonlocal truncated
        if code >= 0:
            data = ctypes.cast(address, ctypes.POINTER(KeyboardEvent)).contents
            # Inspect/store only VK_UP. All other keys pass through unrecorded.
            if data.vkCode == 0x26 and message in (0x100, 0x101, 0x104, 0x105):
                if len(events) < 5000:
                    events.append({"t_s": round(time.monotonic() - started, 4),
                                   "action": "up" if message in (0x101, 0x105) else "down",
                                   "injected": bool(data.flags & 0x10),
                                   "lower_integrity_injected": bool(data.flags & 0x02),
                                   "scan_code": data.scanCode, "extended": bool(data.flags & 0x01)})
                else:
                    truncated = True
        # Always forward input. No key suppression, remapping or injection.
        return user32.CallNextHookEx(hook, code, message, address)

    hook = user32.SetWindowsHookExW(13, callback, kernel32.GetModuleHandleW(None), 0)
    if not hook:
        raise ctypes.WinError(ctypes.get_last_error())
    message = wintypes.MSG()
    stopped_early = False
    print(f"Recording ONLY Up-arrow events for {seconds:g} seconds. Press the physical Up key once and release it, then wait.", flush=True)
    try:
        while time.monotonic() - started < seconds:
            while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            time.sleep(.005)
    except KeyboardInterrupt:
        stopped_early = True
    finally:
        user32.UnhookWindowsHookEx(hook)
    return {"duration_s": round(time.monotonic() - started, 3), "stopped_early": stopped_early,
            "truncated": truncated, "summary": summarize(events, initially_down), "events": events}


def inventory():
    # Names/status only: no command lines, clipboard, environment or typed text.
    script = r'''
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$warnings = @()
$drivers = @()
$filters = $null
try {
  $drivers = @(Get-CimInstance Win32_PnPSignedDriver -Filter "DeviceClass='KEYBOARD'" -ErrorAction Stop | Select-Object DeviceName, DriverProviderName, DriverVersion, InfName)
} catch { $warnings += 'Keyboard driver query failed' }
try {
  $filters = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4D36E96B-E325-11CE-BFC1-08002BE10318}' -ErrorAction Stop | Select-Object UpperFilters, LowerFilters
} catch { $warnings += 'Keyboard filter query failed' }
$pattern = 'autohotkey|powertoys|lghub|logi|razer|synapse|steelseries|icue|armoury|hotkey|keyboard|anydesk|teamviewer|rustdesk|uipath|powerautomate|chatgpt|codex|textinputhost|ctfmon|^code$'
$processes = @(Get-Process | Where-Object { $_.ProcessName -match $pattern } | Select-Object ProcessName, Id)
@{keyboard_drivers=$drivers; keyboard_class_filters=$filters; candidate_processes=$processes; warnings=$warnings} | ConvertTo-Json -Depth 5 -Compress
'''
    try:
        result = subprocess.run(["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, encoding="utf-8", timeout=30, check=True)
        return json.loads(result.stdout.lstrip("\ufeff"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"warnings": ["Could not collect process/driver inventory; event capture is still usable."]}


def main():
    parser = argparse.ArgumentParser(description="Read-only Windows Up-arrow capture and keyboard inventory")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-inventory", action="store_true")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.exit(1, "This diagnostic requires your local Windows machine.\n")
    if not math.isfinite(args.seconds) or not 0 < args.seconds <= 120:
        parser.error("seconds must be between 0 and 120")
    output = args.output or ROOT / ".local" / f"up-key-{time.time_ns()}.json"
    if output.exists():
        parser.exit(1, f"Refusing to overwrite existing report: {output}\n")
    try:
        report = monitor(args.seconds)
        if not args.skip_inventory:
            report["inventory"] = inventory()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report["summary"], indent=2))
        print(f"Report saved to: {output.resolve()}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Diagnostic failed: {exc}\n")


if __name__ == "__main__":
    main()
