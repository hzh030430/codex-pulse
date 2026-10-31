"""Minimal Win32 helpers (ctypes only): locate the Codex desktop window."""
from __future__ import annotations

import ctypes
import os
import winreg
from ctypes import wintypes

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
dwmapi = ctypes.WinDLL('dwmapi')

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_EX_APPWINDOW = 0x00040000
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2
ERROR_ALREADY_EXISTS = 183
MONITOR_DEFAULTTONEAREST = 2

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetWindow.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wintypes.HWND
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetDpiForWindow.restype = ctypes.c_uint
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]


def enable_dpi_awareness() -> None:
    """Per-monitor v2 so window rects and Tk geometry share physical pixels."""
    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.WinDLL('shcore').SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def single_instance(name: str = 'Local\\CodexPulseOverlay') -> bool:
    handle = kernel32.CreateMutexW(None, False, name)
    single_instance._handle = handle  # keep alive for the process lifetime
    return bool(handle) and ctypes.get_last_error() != ERROR_ALREADY_EXISTS


def message_box(text: str, title: str) -> None:
    user32.MessageBoxW(None, text, title, 0x40 | 0x40000)  # MB_ICONINFORMATION | MB_TOPMOST


_path_cache: dict[int, str] = {}


def process_path(pid: int) -> str:
    if pid in _path_cache:
        return _path_cache[pid]
    path = ''
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                path = buf.value
        finally:
            kernel32.CloseHandle(handle)
    if len(_path_cache) > 512:
        _path_cache.clear()
    _path_cache[pid] = path
    return path


def window_pid(hwnd) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def is_codex_desktop(path: str) -> bool:
    """The Electron shell of Codex Desktop (Store / MSIX build or a custom path)."""
    if not path:
        return False
    override = os.environ.get('CODEX_PULSE_EXE')
    if override:
        return os.path.normcase(path) == os.path.normcase(override)
    low = path.lower()
    name = os.path.basename(low)
    if name not in ('codex.exe', 'chatgpt.exe') or '\\resources\\' in low:
        return False
    # Skip the CLI / app-server binaries (app\resources, %LOCALAPPDATA%\OpenAI\Codex\bin).
    return '\\windowsapps\\openai.codex' in low or '\\programs\\codex\\' in low


def frame_rect(hwnd) -> tuple[int, int, int, int] | None:
    """Visible frame (no invisible resize borders): left, top, right, bottom."""
    rect = wintypes.RECT()
    ok = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)) == 0
    if not ok and not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def find_codex_windows() -> list[int]:
    found: list[tuple[int, int]] = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        if not is_codex_desktop(process_path(window_pid(hwnd))):
            return True
        # Electron's main window may have an empty title; its class is stable.
        if user32.GetWindowTextLengthW(hwnd) == 0 and not class_name(hwnd).startswith('Chrome_WidgetWin'):
            return True
        r = frame_rect(hwnd)
        if r and (r[2] - r[0]) >= 320 and (r[3] - r[1]) >= 240:
            found.append(((r[2] - r[0]) * (r[3] - r[1]), hwnd))
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    found.sort(reverse=True)
    return [hwnd for _, hwnd in found]


def describe_windows(match: str = 'openai') -> list[str]:
    """Diagnostics: every top-level window whose process path contains ``match``."""
    rows: list[str] = []
    total = [0]

    def callback(hwnd, _):
        total[0] += 1
        path = process_path(window_pid(hwnd))
        if match not in path.lower():
            return True
        title_len = user32.GetWindowTextLengthW(hwnd)
        rows.append(f'hwnd={hwnd:#x} exe={os.path.basename(path)} visible={bool(user32.IsWindowVisible(hwnd))} '
                    f'owner={bool(user32.GetWindow(hwnd, GW_OWNER))} title_len={title_len} '
                    f'class={class_name(hwnd)} iconic={bool(user32.IsIconic(hwnd))} rect={frame_rect(hwnd)} '
                    f'codex_match={is_codex_desktop(path)}')
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    rows.insert(0, f'top-level windows enumerated: {total[0]}, matching "{match}": {len(rows)}')
    return rows


def foreground_window() -> int:
    return user32.GetForegroundWindow() or 0


def root_window(hwnd) -> int:
    return user32.GetAncestor(hwnd, 2) or hwnd  # GA_ROOT


def is_window(hwnd) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def is_minimized(hwnd) -> bool:
    return bool(user32.IsIconic(hwnd))


def is_visible(hwnd) -> bool:
    return bool(user32.IsWindowVisible(hwnd))


def dpi_scale(hwnd) -> float:
    try:
        dpi = user32.GetDpiForWindow(hwnd)
        return dpi / 96.0 if dpi else 1.0
    except (AttributeError, OSError):
        return 1.0


class _MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT), ('rcWork', wintypes.RECT),
                ('dwFlags', wintypes.DWORD)]


user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]


def work_area(x: int, y: int) -> tuple[int, int, int, int]:
    """Work area (excluding the taskbar) of the monitor containing (x, y)."""
    mon = user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if mon and user32.GetMonitorInfoW(mon, ctypes.byref(info)):
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def style_overlay(hwnd) -> None:
    """No taskbar button, never steals focus, rounded corners on Windows 11."""
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex = (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)
    pref = ctypes.c_int(DWMWCP_ROUND)
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref))


def is_windows11() -> bool:
    import sys
    return sys.getwindowsversion().build >= 22000


def set_border_color(hwnd, hex_color: str) -> bool:
    """Windows 11 DWM border colour (smooth, follows the rounded corners)."""
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    value = ctypes.c_uint(r | (g << 8) | (b << 16))
    return dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(value), ctypes.sizeof(value)) == 0


def apps_use_light_theme() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return bool(winreg.QueryValueEx(key, 'AppsUseLightTheme')[0])
    except OSError:
        return False


# --------------------------------------------------------------------- z-order
GW_HWNDPREV = 3
WS_EX_TOPMOST = 0x00000008
HWND_TOP = 0
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOOWNERZORDER = 0x0200
DWMWA_CLOAKED = 14

user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
SW_HIDE = 0
SW_SHOWNA = 8


def show_no_activate(hwnd, visible: bool) -> None:
    """Show/hide without activating (Tk's deiconify would take focus)."""
    user32.ShowWindow(hwnd, SW_SHOWNA if visible else SW_HIDE)


def is_cloaked(hwnd) -> bool:
    """Hidden by DWM, e.g. on another virtual desktop."""
    value = ctypes.c_int(0)
    ok = dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)) == 0
    return ok and value.value != 0


def is_topmost(hwnd) -> bool:
    return bool(user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)


def window_above(hwnd) -> int:
    return user32.GetWindow(hwnd, GW_HWNDPREV) or 0


def place_above(overlay, target, extra=()) -> None:
    """Put ``overlay`` directly above ``target`` in the z-order without activating it.

    Windows that cover the target therefore also cover the overlay, so it is
    visible exactly when that part of Codex is visible, focused or not.
    ``extra`` are our own windows (e.g. the detail panel) that may sit between.
    """
    prev = window_above(target)
    hops = 0
    while prev and prev in extra and hops < 4:
        prev = window_above(prev)
        hops += 1
    if prev == overlay:
        return
    insert_after = HWND_TOP if (not prev or is_topmost(prev)) else prev
    user32.SetWindowPos(overlay, insert_after, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER)


# ------------------------------------------------------------------ win events
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_DESTROY = 0x8001
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_REORDER = 0x8004
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_CLOAKED = 0x8017
EVENT_OBJECT_UNCLOAKED = 0x8018
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
OBJID_WINDOW = 0

WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND,
                                  wintypes.LONG, wintypes.LONG, wintypes.DWORD, wintypes.DWORD)
user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]


class WinEvents:
    """Out-of-context WinEvent hooks; callbacks run on the thread's message loop (Tk's)."""

    def __init__(self, callback):
        self._callback = callback
        self._proc = WINEVENTPROC(self._dispatch)  # keep a reference alive
        self._global: list = []
        self._process: list = []
        self._pid = None

    def _dispatch(self, _hook, event, hwnd, id_object, _id_child, _thread, _time):
        if id_object != OBJID_WINDOW and event != EVENT_SYSTEM_FOREGROUND:
            return
        try:
            self._callback(event, hwnd or 0)
        except Exception:
            pass

    def _hook(self, lo, hi, pid=0):
        h = user32.SetWinEventHook(lo, hi, None, self._proc, pid, 0,
                                   WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        return [h] if h else []

    def start(self) -> None:
        # Foreground / minimize changes anywhere decide whether Codex is covered.
        self._global = (self._hook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND)
                        + self._hook(EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND))

    def watch_process(self, pid: int | None) -> None:
        """Location / reorder / show / cloak events only for the Codex process (cheap)."""
        if pid == self._pid:
            return
        for h in self._process:
            user32.UnhookWinEvent(h)
        self._process, self._pid = [], pid
        if pid:
            self._process = (self._hook(EVENT_OBJECT_DESTROY, EVENT_OBJECT_REORDER, pid)
                             + self._hook(EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE, pid)
                             + self._hook(EVENT_OBJECT_CLOAKED, EVENT_OBJECT_UNCLOAKED, pid)
                             + self._hook(EVENT_SYSTEM_MOVESIZESTART, EVENT_SYSTEM_MOVESIZEEND, pid))

    def stop(self) -> None:
        for h in self._global + self._process:
            user32.UnhookWinEvent(h)
        self._global, self._process, self._pid = [], [], None
