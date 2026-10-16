#!/usr/bin/env python3
"""
Universal Cross-Platform Auto-Submit Tool
Supports:
  - Windows 10 / 11 (native Win32 API SendInput, MSS, Per-Monitor DPI aware, multi-monitor)
  - Ubuntu / Linux (Wayland via GNOME Mutter + PipeWire)
  - Ubuntu / Linux (X11 via MSS / X11 XTest)
Monitors the screen for the Antigravity confirmation/permission "Submit" button
and automatically clicks it when it appears.
"""

import sys
import os
import time
import signal
import platform
import argparse
import subprocess
from pathlib import Path

# Force UTF-8 on Windows consoles to prevent UnicodeEncodeError with emojis
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Add local site-packages if on Linux user environment
user_site = Path.home() / ".local/lib/python3.12/site-packages"
if user_site.exists() and str(user_site) not in sys.path:
    sys.path.insert(0, str(user_site))

import numpy as np
import cv2

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / ".auto_submit_universal.pid"
LOG_FILE = BASE_DIR / "auto_submit_universal.log"
TEMPLATE_PATH = BASE_DIR / "submit_template.png"

CURRENT_OS = platform.system()  # 'Windows', 'Linux', 'Darwin'


def log(msg: str):
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    line = f"{timestamp} {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        try:
            print(line.encode("ascii", errors="replace").decode("ascii"), flush=True)
        except Exception:
            pass
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_notification(title: str, message: str, visual=False):
    """
    Sends notification without obscuring the screen.
    On Windows, uses a subtle audio chime by default to prevent visual popups 
    from hiding or covering the Submit button in the bottom-right corner.
    """
    try:
        if CURRENT_OS == "Windows":
            # Play a pleasant, non-intrusive audio cue
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass

            # Only show visual balloon popup if explicitly requested
            if visual:
                safe_title = title.replace("'", "''")
                safe_msg = message.replace("'", "''")
                ps_cmd = (
                    f"[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
                    f"[reflection.assembly]::loadwithpartialname('System.Drawing') | Out-Null;"
                    f"$notify = New-Object System.Windows.Forms.NotifyIcon;"
                    f"$notify.Icon = [System.Drawing.SystemIcons]::Information;"
                    f"$notify.Visible = $True;"
                    f"$notify.ShowBalloonTip(2000, '{safe_title}', '{safe_msg}', [System.Windows.Forms.ToolTipIcon]::Info);"
                    f"Start-Sleep -Seconds 2;"
                    f"$notify.Dispose();"
                )
                creation_flags = 0x08000000  # CREATE_NO_WINDOW
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags
                )
        elif CURRENT_OS == "Linux":
            subprocess.Popen(["notify-send", "-a", "Auto-Submit", "-u", "low", title, message])
    except Exception:
        pass


# ==============================================================================
# 1. WINDOWS BACKEND
# ==============================================================================
class WindowsBackend:
    """High-performance Windows screen capture and click injection using Win32 API."""
    def __init__(self, monitor_index=0, target_window=None):
        import ctypes
        from ctypes import wintypes
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.target_window = target_window

        # 1. Ensure access to the interactive desktop (WinSta0\\Default)
        # Required when running in background, IDE terminal, or service
        try:
            hw = self.user32.OpenWindowStationW("WinSta0", False, 0x10000000)
            if hw:
                self.user32.SetProcessWindowStation(hw)
            hd = self.user32.OpenDesktopW("Default", 0, False, 0x10000000)
            if hd:
                self.user32.SetThreadDesktop(hd)
        except Exception:
            pass

        # 2. Modern Per-Monitor DPI Awareness v2
        try:
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    self.user32.SetProcessDPIAware()
                except Exception:
                    pass

        # 3. MSS screen capture
        import mss
        self.sct = getattr(mss, "MSS", mss.mss)()
        self.monitor_index = monitor_index

        if monitor_index == 0 or monitor_index >= len(self.sct.monitors):
            # All monitors combined (virtual desktop)
            self.monitor = self.sct.monitors[0]
        else:
            self.monitor = self.sct.monitors[monitor_index]

        self.offset_x = self.monitor["left"]
        self.offset_y = self.monitor["top"]

    def get_latest_frame(self, timeout_sec=0.5):
        # If target window is specified, crop to window rect
        if self.target_window:
            rect = self._find_window_rect(self.target_window)
            if rect:
                wx, wy, ww, wh = rect
                try:
                    sct_img = self.sct.grab({"left": wx, "top": wy, "width": ww, "height": wh})
                    self.offset_x = wx
                    self.offset_y = wy
                    frame = np.array(sct_img)
                    return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                except Exception:
                    pass

        # Otherwise grab full monitor
        self.offset_x = self.monitor["left"]
        self.offset_y = self.monitor["top"]
        try:
            sct_img = self.sct.grab(self.monitor)
            frame = np.array(sct_img)
            return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        except Exception:
            # Fallback to PIL ImageGrab if MSS encounters GDI lock
            try:
                from PIL import ImageGrab
                bbox = (
                    self.monitor["left"],
                    self.monitor["top"],
                    self.monitor["left"] + self.monitor["width"],
                    self.monitor["top"] + self.monitor["height"]
                )
                img = ImageGrab.grab(bbox=bbox)
                frame = np.array(img)
                return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            except Exception:
                return None

    def _find_window_rect(self, name_pattern: str):
        import ctypes
        from ctypes import wintypes
        u = self.user32
        target_rect = None

        def enum_cb(hwnd, _):
            nonlocal target_rect
            if u.IsWindowVisible(hwnd) and not u.IsIconic(hwnd):
                length = u.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buf = ctypes.create_unicode_buffer(length + 1)
                    u.GetWindowTextW(hwnd, buf, length + 1)
                    if name_pattern.lower() in buf.value.lower():
                        rect = wintypes.RECT()
                        u.GetWindowRect(hwnd, ctypes.byref(rect))
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        if w > 100 and h > 100:
                            target_rect = (rect.left, rect.top, w, h)
                            return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows(WNDENUMPROC(enum_cb), 0)
        return target_rect

    def click_at(self, x: float, y: float):
        """Click at (x, y) relative to captured frame, converted to global virtual screen coordinates."""
        global_x = int(round(x + self.offset_x))
        global_y = int(round(y + self.offset_y))

        import ctypes
        from ctypes import wintypes

        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)
            ]

        class _INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT)
            ]

        class INPUT(ctypes.Structure):
            _fields_ = [
                ("type", wintypes.DWORD),
                ("union", _INPUT_UNION)
            ]

        INPUT_MOUSE = 0
        MOUSEEVENTF_LEFTDOWN = 0x0002
        MOUSEEVENTF_LEFTUP = 0x0004

        # 1. Move cursor to absolute target position
        self.user32.SetCursorPos(global_x, global_y)
        time.sleep(0.04)

        # 2. Left click down via SendInput
        inp_down = INPUT(INPUT_MOUSE, _INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)))
        inp_up = INPUT(INPUT_MOUSE, _INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)))

        r1 = self.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
        time.sleep(0.05)
        r2 = self.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))

        # Fallback to mouse_event if SendInput did not dispatch
        if r1 == 0 or r2 == 0:
            self.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.05)
            self.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        return True

    def close(self):
        if hasattr(self, "sct") and self.sct:
            try:
                self.sct.close()
            except Exception:
                pass


# ==============================================================================
# 2. LINUX X11 BACKEND
# ==============================================================================
class LinuxX11Backend:
    """Linux X11 backend using MSS and X11 XTest / xdotool."""
    def __init__(self, monitor_index=0):
        import mss
        self.sct = getattr(mss, "MSS", mss.mss)()
        self.monitor = self.sct.monitors[monitor_index if monitor_index < len(self.sct.monitors) else 0]
        self.offset_x = self.monitor["left"]
        self.offset_y = self.monitor["top"]

        # Load libX11 and libXtst for direct hardware clicking
        import ctypes
        try:
            self.x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            self.xtst = ctypes.cdll.LoadLibrary("libXtst.so.6")
            self.display = self.x11.XOpenDisplay(None)
        except Exception:
            self.x11 = None
            self.xtst = None
            self.display = None

    def get_latest_frame(self, timeout_sec=0.5):
        sct_img = self.sct.grab(self.monitor)
        frame = np.array(sct_img)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def click_at(self, x: float, y: float):
        ix = int(round(x + self.offset_x))
        iy = int(round(y + self.offset_y))
        if self.display and self.xtst:
            root = self.x11.XDefaultRootWindow(self.display)
            self.x11.XWarpPointer(self.display, 0, root, 0, 0, 0, 0, ix, iy)
            self.x11.XFlush(self.display)
            time.sleep(0.04)
            self.xtst.XTestFakeButtonEvent(self.display, 1, True, 0)
            self.x11.XFlush(self.display)
            time.sleep(0.05)
            self.xtst.XTestFakeButtonEvent(self.display, 1, False, 0)
            self.x11.XFlush(self.display)
            return True
        else:
            subprocess.run(["xdotool", "mousemove", str(ix), str(iy), "click", "1"], check=False)
            return True

    def close(self):
        if hasattr(self, "sct") and self.sct:
            try:
                self.sct.close()
            except Exception:
                pass
        if hasattr(self, "display") and self.display:
            try:
                self.x11.XCloseDisplay(self.display)
            except Exception:
                pass


# ==============================================================================
# 3. LINUX WAYLAND BACKEND (GNOME Mutter + PipeWire)
# ==============================================================================
class LinuxWaylandBackend:
    """Linux Wayland backend using Mutter RemoteDesktop + ScreenCast PipeWire."""
    def __init__(self, w=1920, h=1080):
        self._ensure_remote_desktop_input()
        self.w, self.h = w, h

        import dbus
        from dbus.mainloop.glib import DBusGMainLoop
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst, GLib

        Gst.init(None)
        DBusGMainLoop(set_as_default=True)
        self.GLib = GLib
        self.Gst = Gst
        self.bus = dbus.SessionBus()
        self.loop = GLib.MainLoop()

        self.rd_sess = None
        self.sc_sess = None
        self.stream_path = None
        self.pipeline = None
        self.sink = None
        self.node_id = None
        self._init_session()

    def _ensure_remote_desktop_input(self):
        try:
            subprocess.run(["gsettings", "set", "org.gnome.desktop.remote-desktop.rdp", "view-only", "false"], check=False)
            subprocess.run(["gsettings", "set", "org.gnome.desktop.remote-desktop.vnc", "view-only", "false"], check=False)
        except Exception:
            pass

    def _init_session(self):
        import dbus
        rd_obj = self.bus.get_object("org.gnome.Mutter.RemoteDesktop", "/org/gnome/Mutter/RemoteDesktop")
        rd = dbus.Interface(rd_obj, "org.gnome.Mutter.RemoteDesktop")
        rd_path = rd.CreateSession()
        rd_sess_obj = self.bus.get_object("org.gnome.Mutter.RemoteDesktop", rd_path)
        self.rd_sess = dbus.Interface(rd_sess_obj, "org.gnome.Mutter.RemoteDesktop.Session")

        rd_props = dbus.Interface(rd_sess_obj, "org.freedesktop.DBus.Properties")
        session_id = rd_props.Get("org.gnome.Mutter.RemoteDesktop.Session", "SessionId")

        sc_obj = self.bus.get_object("org.gnome.Mutter.ScreenCast", "/org/gnome/Mutter/ScreenCast")
        sc = dbus.Interface(sc_obj, "org.gnome.Mutter.ScreenCast")
        sc_path = sc.CreateSession({"remote-desktop-session-id": session_id})
        sc_sess_obj = self.bus.get_object("org.gnome.Mutter.ScreenCast", sc_path)
        self.sc_sess = dbus.Interface(sc_sess_obj, "org.gnome.Mutter.ScreenCast.Session")

        self.stream_path = self.sc_sess.RecordArea(0, 0, self.w, self.h, {})

        def on_stream_added(node_id):
            self.node_id = int(node_id)
            self._start_pipeline(self.node_id)

        self.bus.add_signal_receiver(
            on_stream_added,
            dbus_interface="org.gnome.Mutter.ScreenCast.Stream",
            signal_name="PipeWireStreamAdded",
            path=self.stream_path
        )
        self.rd_sess.Start()

    def _start_pipeline(self, node_id: int):
        pipeline_str = (
            f"pipewiresrc path={node_id} ! "
            f"videoconvert ! video/x-raw,format=BGR ! "
            f"appsink name=sink emit-signals=false max-buffers=1 drop=true"
        )
        self.pipeline = self.Gst.parse_launch(pipeline_str)
        self.sink = self.pipeline.get_by_name("sink")
        self.pipeline.set_state(self.Gst.State.PLAYING)

    def get_latest_frame(self, timeout_sec=1.5):
        start = time.time()
        ctx = self.loop.get_context()
        while time.time() - start < timeout_sec:
            ctx.iteration(False)
            if self.sink:
                latest_sample = None
                while True:
                    s = self.sink.emit("try-pull-sample", 0)
                    if s:
                        latest_sample = s
                    else:
                        break

                if latest_sample:
                    caps = latest_sample.get_caps()
                    structure = caps.get_structure(0)
                    w, h = structure.get_value("width"), structure.get_value("height")
                    buf = latest_sample.get_buffer()
                    success, map_info = buf.map(self.Gst.MapFlags.READ)
                    if success:
                        frame = np.ndarray((h, w, 3), buffer=map_info.data, dtype=np.uint8).copy()
                        buf.unmap(map_info)
                        return frame
            time.sleep(0.04)
        return None

    def click_at(self, x: float, y: float):
        BTN_LEFT = 0x110
        if not self.rd_sess or not self.stream_path:
            return False
        try:
            self.rd_sess.NotifyPointerMotionAbsolute(self.stream_path, float(x), float(y))
            time.sleep(0.06)
            self.rd_sess.NotifyPointerButton(BTN_LEFT, True)
            time.sleep(0.06)
            self.rd_sess.NotifyPointerButton(BTN_LEFT, False)
            return True
        except Exception as e:
            log(f"Error during Wayland click: {e}")
            return False

    def close(self):
        if self.pipeline:
            try:
                self.pipeline.set_state(self.Gst.State.NULL)
            except Exception:
                pass
        if self.rd_sess:
            try:
                self.rd_sess.Stop()
            except Exception:
                pass


# ==============================================================================
# 4. BACKEND FACTORY
# ==============================================================================
def get_backend(monitor=0, window=None):
    """Automatically selects the best backend for the current operating system."""
    if CURRENT_OS == "Windows":
        log(f"🖥️ Detected OS: Windows (using native Win32 + MSS backend, monitor={monitor})")
        return WindowsBackend(monitor_index=monitor, target_window=window)
    elif CURRENT_OS == "Linux":
        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            log("🖥️ Detected OS: Linux Wayland (using GNOME Mutter RemoteDesktop backend)")
            return LinuxWaylandBackend()
        else:
            log(f"🖥️ Detected OS: Linux X11 (using X11 backend, monitor={monitor})")
            return LinuxX11Backend(monitor_index=monitor)
    else:
        raise NotImplementedError(f"Operating system {CURRENT_OS} is not supported.")


# ==============================================================================
# 5. TEMPLATE DETECTOR
# ==============================================================================
class SubmitButtonDetector:
    """
    Robust multi-scale, mask-aware template matcher for the Antigravity Submit button.
    Supports scaling from 80% to 200% (covering Windows 100%, 125%, 150%, 175%, 200% DPI).
    Uses masked matching to ignore background corner colors.
    """
    def __init__(self, template_path=TEMPLATE_PATH, threshold=0.75):
        if not template_path.exists():
            raise FileNotFoundError(f"Template not found at: {template_path}")
        self.template_bgr = cv2.imread(str(template_path))
        self.th_h, self.th_w = self.template_bgr.shape[:2]
        self.threshold = threshold

        # Generate corner mask: ignore dark corners [28, 28, 28] around rounded button
        self.mask = np.ones((self.th_h, self.th_w), dtype=np.uint8) * 255
        dark_corners = (self.template_bgr[:, :, 0] < 40) & (self.template_bgr[:, :, 1] < 40) & (self.template_bgr[:, :, 2] < 40)
        self.mask[dark_corners] = 0

        # Grayscale template for ultra-fast matching
        self.template_gray = cv2.cvtColor(self.template_bgr, cv2.COLOR_BGR2GRAY)

        # Pre-compute scaled variations across common display scales
        # Windows: 100% (1.0), 125% (1.25), 150% (1.5), 175% (1.75), 200% (2.0)
        # Linux/Zoom: 80% (0.8), 90% (0.9), 110% (1.1)
        self.scales = [1.0, 1.25, 1.5, 0.9, 1.1, 0.8, 1.75, 2.0]
        self.cached_templates = []
        for s in self.scales:
            tw = max(10, int(round(self.th_w * s)))
            th = max(10, int(round(self.th_h * s)))
            resized_gray = cv2.resize(self.template_gray, (tw, th), interpolation=cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR)
            resized_mask = cv2.resize(self.mask, (tw, th), interpolation=cv2.INTER_NEAREST)
            self.cached_templates.append({
                "scale": s,
                "w": tw,
                "h": th,
                "gray": resized_gray,
                "mask": resized_mask
            })

    def detect(self, frame, y_start_ratio=0.0):
        """
        Scans frame for the Submit button.
        y_start_ratio defaults to 0.0 (full screen) to ensure no dialogs are missed.
        Returns (found: bool, (cx, cy), max_score, (x, y, w, h))
        """
        h, w = frame.shape[:2]
        y_start = int(h * y_start_ratio)
        roi = frame[y_start:, :]
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        best_score = -1.0
        best_loc = (0, 0)
        best_wh = (self.th_w, self.th_h)

        # 1. Test 1.0x scale first (fastest, standard scale)
        primary = self.cached_templates[0]
        if roi_gray.shape[0] >= primary["h"] and roi_gray.shape[1] >= primary["w"]:
            res = cv2.matchTemplate(roi_gray, primary["gray"], cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            best_score = max_val
            best_loc = max_loc
            best_wh = (primary["w"], primary["h"])

            if best_score >= self.threshold:
                rx, ry = best_loc
                bw, bh = best_wh
                abs_x = rx
                abs_y = y_start + ry
                cx = abs_x + bw // 2
                cy = abs_y + bh // 2
                return True, (cx, cy), best_score, (abs_x, abs_y, bw, bh)

        # 2. Multi-scale search across other display scales (e.g. 1.25x, 1.5x)
        for t in self.cached_templates[1:]:
            th, tw = t["h"], t["w"]
            if roi_gray.shape[0] < th or roi_gray.shape[1] < tw:
                continue
            res = cv2.matchTemplate(roi_gray, t["gray"], cv2.TM_CCOEFF_NORMED)
            _, s_max_val, _, s_max_loc = cv2.minMaxLoc(res)
            if s_max_val > best_score:
                best_score = s_max_val
                best_loc = s_max_loc
                best_wh = (tw, th)
                if best_score >= self.threshold:
                    break

        if best_score >= self.threshold:
            rx, ry = best_loc
            bw, bh = best_wh
            abs_x = rx
            abs_y = y_start + ry
            cx = abs_x + bw // 2
            cy = abs_y + bh // 2
            return True, (cx, cy), best_score, (abs_x, abs_y, bw, bh)

        return False, None, best_score, None


# ==============================================================================
# 6. MONITOR ENGINE & PROCESS MANAGEMENT
# ==============================================================================
class UniversalAutoSubmitMonitor:
    def __init__(self, interval=0.35, threshold=0.75, cooldown=1.5, dry_run=False,
                 notify=True, visual_notify=False, monitor=0, window=None, template=TEMPLATE_PATH):
        self.interval = interval
        self.threshold = threshold
        self.cooldown = cooldown
        self.dry_run = dry_run
        self.notify = notify
        self.visual_notify = visual_notify
        self.monitor_index = monitor
        self.window = window
        self.running = False
        self.last_click_time = 0.0
        self.detector = SubmitButtonDetector(template_path=template, threshold=threshold)

    def run(self):
        log(f"🚀 Universal Auto-Submit running on {CURRENT_OS} (interval={self.interval}s, threshold={self.threshold})")
        self.running = True

        def sig_handler(sig, frame):
            log("🛑 Received shutdown signal, stopping...")
            self.running = False

        try:
            signal.signal(signal.SIGINT, sig_handler)
            signal.signal(signal.SIGTERM, sig_handler)
        except Exception:
            pass

        backend = None
        try:
            backend = get_backend(monitor=self.monitor_index, window=self.window)
            while self.running:
                frame = backend.get_latest_frame(timeout_sec=0.8)
                if frame is not None:
                    found, center, score, bbox = self.detector.detect(frame)
                    if found:
                        cx, cy = center
                        now = time.time()
                        if now - self.last_click_time >= self.cooldown:
                            self.last_click_time = now
                            log(f"🎯 Submit button detected at ({cx}, {cy}) [Score: {score:.3f}]")
                            if self.dry_run:
                                log("🔎 [DRY-RUN] Click skipped.")
                            else:
                                success = backend.click_at(cx, cy)
                                if success:
                                    log(f"✅ Click successfully sent to ({cx}, {cy})")
                                    if self.notify:
                                        send_notification("Auto-Submit", f"Clicked Submit at ({cx}, {cy})", visual=self.visual_notify)
                                time.sleep(0.4)
                time.sleep(self.interval)
        except KeyboardInterrupt:
            log("🛑 Interrupted by user.")
        finally:
            if backend:
                backend.close()
            PID_FILE.unlink(missing_ok=True)
            log("✨ Auto-Submit stopped.")


def test_detection(threshold=0.75, monitor=0, window=None, template=TEMPLATE_PATH):
    print(f"📸 Testing capture on {CURRENT_OS}...")
    backend = get_backend(monitor=monitor, window=window)
    try:
        frame = backend.get_latest_frame(timeout_sec=2.0)
        if frame is None:
            print("❌ Failed to grab screen frame.")
            return

        detector = SubmitButtonDetector(template_path=template, threshold=threshold)
        found, center, score, bbox = detector.detect(frame)

        debug_img = frame.copy()
        if found:
            cx, cy = center
            x, y, w, h = bbox
            cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(debug_img, (cx, cy), 6, (0, 0, 255), -1)
            cv2.putText(debug_img, f"SUBMIT: {score:.3f}", (x, max(20, y - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            print(f"🎉 FOUND Submit button at center ({cx}, {cy}) with confidence: {score:.4f}!")
        else:
            print(f"ℹ️ Submit button NOT found on screen. Highest match score: {score:.4f} (threshold: {threshold})")

        out_path = BASE_DIR / "debug_universal_test.png"
        cv2.imwrite(str(out_path), debug_img)
        print(f"🖼️ Debug snapshot saved to: {out_path}")
    finally:
        backend.close()


def get_pid():
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if CURRENT_OS == "Windows":
                # Check if process is still running on Windows
                import ctypes
                k = ctypes.windll.kernel32
                hproc = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if hproc:
                    k.CloseHandle(hproc)
                    return pid
            else:
                os.kill(pid, 0)
                return pid
        except Exception:
            PID_FILE.unlink(missing_ok=True)
    return None


def cmd_start(args):
    pid = get_pid()
    if pid:
        print(f"⚠️ Auto-Submit is ALREADY running (PID: {pid}).")
        return

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "run",
        "--interval", str(args.interval),
        "--threshold", str(args.threshold),
        "--cooldown", str(args.cooldown),
        "--monitor", str(args.monitor)
    ]
    if args.dry_run:
        cmd.append("--dry-run")
    if not args.notify:
        cmd.append("--no-notify")
    if args.window:
        cmd.extend(["--window", args.window])

    if CURRENT_OS == "Windows":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        CREATE_NO_WINDOW = 0x08000000
        flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        with open(LOG_FILE, "a", encoding="utf-8") as log_f:
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=log_f,
                creationflags=flags,
                close_fds=True
            )
    else:
        with open(LOG_FILE, "a", encoding="utf-8") as log_f:
            proc = subprocess.Popen(
                cmd,
                stdout=log_f,
                stderr=log_f,
                start_new_session=True
            )

    PID_FILE.write_text(str(proc.pid))
    print(f"✅ Auto-Submit started in background (PID: {proc.pid}).")
    print(f"📄 Logs: {LOG_FILE}")
    send_notification("Auto-Submit Active", "Continuous screen monitoring is running.")


def cmd_stop():
    pid = get_pid()
    if not pid:
        if CURRENT_OS == "Windows":
            subprocess.run(["taskkill", "/F", "/FI", "WINDOWTITLE eq Antigravity Auto-Submit*"], check=False)
        else:
            subprocess.run(["pkill", "-f", "auto_submit_universal.py run"], check=False)
        PID_FILE.unlink(missing_ok=True)
        print("ℹ️ Auto-Submit stopped.")
        return

    print(f"🛑 Stopping Auto-Submit (PID: {pid})...")
    try:
        if CURRENT_OS == "Windows":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
            for _ in range(25):
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
            else:
                os.kill(pid, signal.SIGKILL)
    except Exception as e:
        print(f"Error stopping process: {e}")

    PID_FILE.unlink(missing_ok=True)
    print("✅ Stopped.")
    send_notification("Auto-Submit Stopped", "Screen monitoring stopped.")


def cmd_status():
    pid = get_pid()
    if pid:
        print(f"🟢 Status: RUNNING (PID: {pid})")
    else:
        print("⚪ Status: STOPPED")

    if LOG_FILE.exists():
        print(f"\n📄 Recent logs ({LOG_FILE}):")
        try:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-10:]
            for line in lines:
                print(f"   {line}")
        except Exception:
            pass


# ==============================================================================
# 7. MAIN CLI PARSER
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Universal Auto-Submit Tool (Windows / Ubuntu Linux)")
    subparsers = parser.add_subparsers(dest="command")

    for cmd_name in ["run", "start"]:
        sub = subparsers.add_parser(cmd_name, help=f"'{cmd_name}' monitor ({'foreground' if cmd_name == 'run' else 'background daemon'})")
        sub.add_argument("--interval", type=float, default=0.35, help="Check interval in seconds (default: 0.35)")
        sub.add_argument("--threshold", type=float, default=0.75, help="Detection threshold (default: 0.75)")
        sub.add_argument("--cooldown", type=float, default=1.5, help="Click cooldown in seconds (default: 1.5)")
        sub.add_argument("--dry-run", action="store_true", help="Detect but do not click")
        sub.add_argument("--no-notify", dest="notify", action="store_false", help="Disable all notifications")
        sub.add_argument("--visual-notify", action="store_true", help="Show visual balloon popup (not recommended if it covers the button)")
        sub.add_argument("--monitor", type=int, default=0, help="Monitor index (0 = all screens, 1 = primary)")
        sub.add_argument("--window", type=str, default=None, help="Target window title substring (e.g. Antigravity)")
        sub.add_argument("--template", type=Path, default=TEMPLATE_PATH, help="Path to button template image")

    subparsers.add_parser("stop", help="Stop background daemon")
    subparsers.add_parser("status", help="Show current daemon status")

    test_parser = subparsers.add_parser("test", help="Test detection on current screen without clicking")
    test_parser.add_argument("--threshold", type=float, default=0.75, help="Detection threshold (default: 0.75)")
    test_parser.add_argument("--monitor", type=int, default=0, help="Monitor index (0 = all screens, 1 = primary)")
    test_parser.add_argument("--window", type=str, default=None, help="Target window title substring (e.g. Antigravity)")
    test_parser.add_argument("--template", type=Path, default=TEMPLATE_PATH, help="Path to button template image")

    args = parser.parse_args()

    if not args.command:
        # Default to 'run' if no subcommand provided
        args.command = "run"
        args.interval = 0.35
        args.threshold = 0.75
        args.cooldown = 1.5
        args.dry_run = False
        args.visual_notify = False
        args.monitor = 0
        args.window = None
        args.template = TEMPLATE_PATH

    if args.command == "run":
        monitor = UniversalAutoSubmitMonitor(
            interval=args.interval,
            threshold=args.threshold,
            cooldown=args.cooldown,
            dry_run=args.dry_run,
            notify=args.notify,
            visual_notify=getattr(args, "visual_notify", False),
            monitor=args.monitor,
            window=args.window,
            template=args.template
        )
        monitor.run()
    elif args.command == "start":
        cmd_start(args)
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "test":
        test_detection(
            threshold=args.threshold,
            monitor=args.monitor,
            window=args.window,
            template=args.template
        )


if __name__ == "__main__":
    main()
