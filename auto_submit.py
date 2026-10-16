#!/usr/bin/env python3
"""
Antigravity Auto-Submit Daemon (Cross-Platform: Windows, Wayland, X11)
Monitors the screen for the Antigravity confirmation/permission "Submit" button
and automatically clicks it when it appears.
"""

import sys
import platform

CURRENT_OS = platform.system()

if CURRENT_OS == "Windows":
    # On Windows, delegate to the fully-featured Windows engine in auto_submit_universal
    import auto_submit_universal

    if __name__ == "__main__":
        auto_submit_universal.main()
else:
    # Linux (Wayland / X11) Native Daemon
    import os
    import time
    import signal
    import argparse
    import subprocess
    from pathlib import Path

    user_site = Path.home() / ".local/lib/python3.12/site-packages"
    if user_site.exists() and str(user_site) not in sys.path:
        sys.path.insert(0, str(user_site))

    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst, GLib
    import numpy as np
    import cv2

    Gst.init(None)
    DBusGMainLoop(set_as_default=True)

    BASE_DIR = Path(__file__).resolve().parent
    PID_FILE = BASE_DIR / ".auto_submit.pid"
    LOG_FILE = BASE_DIR / "auto_submit.log"
    TEMPLATE_PATH = BASE_DIR / "submit_template.png"

    BTN_LEFT = 0x110

    def ensure_remote_desktop_input():
        try:
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.remote-desktop.rdp", "view-only", "false"],
                check=False
            )
            subprocess.run(
                ["gsettings", "set", "org.gnome.desktop.remote-desktop.vnc", "view-only", "false"],
                check=False
            )
        except Exception:
            pass

    def log(msg: str):
        timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
        line = f"{timestamp} {msg}"
        print(line, flush=True)
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def send_notification(title: str, message: str):
        try:
            subprocess.Popen(["notify-send", "-a", "Auto-Submit", "-u", "low", title, message])
        except Exception:
            pass

    class WaylandController:
        def __init__(self, w=1920, h=1080):
            ensure_remote_desktop_input()
            self.w, self.h = w, h
            self.bus = dbus.SessionBus()
            self.loop = GLib.MainLoop()
            self.rd_sess = None
            self.sc_sess = None
            self.stream_path = None
            self.pipeline = None
            self.sink = None
            self.node_id = None
            self._init_session()

        def _init_session(self):
            rd_obj = self.bus.get_object('org.gnome.Mutter.RemoteDesktop', '/org/gnome/Mutter/RemoteDesktop')
            rd = dbus.Interface(rd_obj, 'org.gnome.Mutter.RemoteDesktop')
            rd_path = rd.CreateSession()
            rd_sess_obj = self.bus.get_object('org.gnome.Mutter.RemoteDesktop', rd_path)
            self.rd_sess = dbus.Interface(rd_sess_obj, 'org.gnome.Mutter.RemoteDesktop.Session')

            rd_props = dbus.Interface(rd_sess_obj, 'org.freedesktop.DBus.Properties')
            session_id = rd_props.Get('org.gnome.Mutter.RemoteDesktop.Session', 'SessionId')

            sc_obj = self.bus.get_object('org.gnome.Mutter.ScreenCast', '/org/gnome/Mutter/ScreenCast')
            sc = dbus.Interface(sc_obj, 'org.gnome.Mutter.ScreenCast')
            sc_path = sc.CreateSession({'remote-desktop-session-id': session_id})
            sc_sess_obj = self.bus.get_object('org.gnome.Mutter.ScreenCast', sc_path)
            self.sc_sess = dbus.Interface(sc_sess_obj, 'org.gnome.Mutter.ScreenCast.Session')

            self.stream_path = self.sc_sess.RecordArea(0, 0, self.w, self.h, {})

            def on_stream_added(node_id):
                self.node_id = int(node_id)
                self._start_pipeline(self.node_id)

            self.bus.add_signal_receiver(
                on_stream_added,
                dbus_interface='org.gnome.Mutter.ScreenCast.Stream',
                signal_name='PipeWireStreamAdded',
                path=self.stream_path
            )
            self.rd_sess.Start()

        def _start_pipeline(self, node_id: int):
            pipeline_str = (
                f"pipewiresrc path={node_id} ! "
                f"videoconvert ! video/x-raw,format=BGR ! "
                f"appsink name=sink emit-signals=false max-buffers=1 drop=true"
            )
            self.pipeline = Gst.parse_launch(pipeline_str)
            self.sink = self.pipeline.get_by_name('sink')
            self.pipeline.set_state(Gst.State.PLAYING)

        def get_latest_frame(self, timeout_sec=1.5):
            start = time.time()
            ctx = self.loop.get_context()
            while time.time() - start < timeout_sec:
                ctx.iteration(False)
                if self.sink:
                    latest_sample = None
                    while True:
                        s = self.sink.emit('try-pull-sample', 0)
                        if s:
                            latest_sample = s
                        else:
                            break

                    if latest_sample:
                        caps = latest_sample.get_caps()
                        structure = caps.get_structure(0)
                        w, h = structure.get_value('width'), structure.get_value('height')
                        buf = latest_sample.get_buffer()
                        success, map_info = buf.map(Gst.MapFlags.READ)
                        if success:
                            frame = np.ndarray((h, w, 3), buffer=map_info.data, dtype=np.uint8).copy()
                            buf.unmap(map_info)
                            return frame
                time.sleep(0.04)
            return None

        def click_at(self, x: float, y: float):
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
                log(f"Error during click dispatch: {e}")
                return False

        def close(self):
            if self.pipeline:
                try:
                    self.pipeline.set_state(Gst.State.NULL)
                except Exception:
                    pass
            if self.rd_sess:
                try:
                    self.rd_sess.Stop()
                except Exception:
                    pass

    class SubmitButtonDetector:
        def __init__(self, template_path=TEMPLATE_PATH, threshold=0.75):
            if not template_path.exists():
                raise FileNotFoundError(f"Template not found at: {template_path}")
            self.template = cv2.imread(str(template_path))
            self.th_h, self.th_w = self.template.shape[:2]
            self.threshold = threshold
            self.template_gray = cv2.cvtColor(self.template, cv2.COLOR_BGR2GRAY)
            self.scales = [1.0, 1.25, 1.5, 0.9, 1.1, 0.8, 1.75, 2.0]
            self.cached_templates = []
            for s in self.scales:
                tw = max(10, int(round(self.th_w * s)))
                th = max(10, int(round(self.th_h * s)))
                resized_gray = cv2.resize(self.template_gray, (tw, th))
                self.cached_templates.append({"w": tw, "h": th, "gray": resized_gray})

        def detect(self, frame, y_start=0):
            h, w = frame.shape[:2]
            roi = frame[y_start:, :]
            roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

            best_score = -1.0
            best_loc = (0, 0)
            best_wh = (self.th_w, self.th_h)

            for t in self.cached_templates:
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

    class AutoSubmitMonitor:
        def __init__(self, interval=0.35, threshold=0.75, cooldown=1.5, dry_run=False, notify=True):
            self.interval = interval
            self.threshold = threshold
            self.cooldown = cooldown
            self.dry_run = dry_run
            self.notify = notify
            self.running = False
            self.last_click_time = 0.0
            self.controller = None
            self.detector = SubmitButtonDetector(threshold=threshold)

        def trigger_click(self, cx: int, cy: int, score: float):
            now = time.time()
            if now - self.last_click_time < self.cooldown:
                return False

            self.last_click_time = now
            log(f"🎯 Submit button detected at ({cx}, {cy}) [Confidence: {score:.3f}]")

            if self.dry_run:
                log("🔎 [DRY-RUN] Click action skipped.")
                return True

            success = self.controller.click_at(cx, cy)
            if success:
                log(f"✅ Physical mouse click sent to ({cx}, {cy})")
                if self.notify:
                    send_notification(
                        "Auto-Submit Clicked",
                        f"Clicked Submit button at ({cx}, {cy}) [Score: {score:.2f}]"
                    )
            else:
                log(f"⚠️ Failed to deliver click to ({cx}, {cy})")
            return success

        def run(self):
            log(f"🚀 Continuous monitoring active (interval={self.interval}s, threshold={self.threshold}, cooldown={self.cooldown}s)")
            self.running = True

            def sig_handler(sig, frame):
                log("🛑 Received shutdown signal, stopping...")
                self.running = False

            signal.signal(signal.SIGINT, sig_handler)
            signal.signal(signal.SIGTERM, sig_handler)

            while self.running:
                try:
                    self.controller = WaylandController()
                    log("📡 Wayland ScreenCast & Input session established.")

                    while self.running:
                        frame = self.controller.get_latest_frame(timeout_sec=0.8)
                        if frame is not None:
                            found, center, score, bbox = self.detector.detect(frame)
                            if found:
                                cx, cy = center
                                self.trigger_click(cx, cy, score)
                                time.sleep(0.4)
                        time.sleep(self.interval)

                except Exception as e:
                    log(f"⚠️ Session notice: {e}. Reconnecting in 1.5s...")
                    time.sleep(1.5)
                finally:
                    if self.controller:
                        self.controller.close()
                        self.controller = None

            log("✨ Auto-Submit monitor terminated gracefully.")

    def test_detection(threshold=0.75):
        print("📸 Capturing 1 live frame via Wayland ScreenCast...")
        controller = WaylandController()
        try:
            frame = controller.get_latest_frame(timeout_sec=3.0)
            if frame is None:
                print("❌ Failed to grab screen frame.")
                return

            detector = SubmitButtonDetector(threshold=threshold)
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
                print(f"ℹ️ Submit button NOT visible on current screen. Highest match score: {score:.4f} (threshold: {threshold})")

            out_path = BASE_DIR / "debug_last_check.png"
            cv2.imwrite(str(out_path), debug_img)
            print(f"🖼️ Debug snapshot saved to: {out_path}")
        finally:
            controller.close()

    def get_pid():
        if PID_FILE.exists():
            try:
                pid = int(PID_FILE.read_text().strip())
                os.kill(pid, 0)
                return pid
            except (ProcessLookupError, ValueError):
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
            "--cooldown", str(args.cooldown)
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        if not args.notify:
            cmd.append("--no-notify")

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
            subprocess.run(["pkill", "-f", "auto_submit.py run"], check=False)
            PID_FILE.unlink(missing_ok=True)
            print("ℹ️ Auto-Submit stopped.")
            return

        print(f"🛑 Stopping Auto-Submit (PID: {pid})...")
        try:
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
        subprocess.run(["pkill", "-f", "auto_submit.py run"], check=False)
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

    def main():
        parser = argparse.ArgumentParser(description="Antigravity Auto-Submit Daemon")
        subparsers = parser.add_subparsers(dest="command")

        run_parser = subparsers.add_parser("run", help="Run in foreground (continuous)")
        run_parser.add_argument("--interval", type=float, default=0.35, help="Check interval in seconds (default: 0.35)")
        run_parser.add_argument("--threshold", type=float, default=0.75, help="Detection threshold (default: 0.75)")
        run_parser.add_argument("--cooldown", type=float, default=1.5, help="Click cooldown in seconds (default: 1.5)")
        run_parser.add_argument("--dry-run", action="store_true", help="Detect but do not click")
        run_parser.add_argument("--no-notify", dest="notify", action="store_false", help="Disable notifications")

        start_parser = subparsers.add_parser("start", help="Start background daemon")
        start_parser.add_argument("--interval", type=float, default=0.35, help="Check interval in seconds (default: 0.35)")
        start_parser.add_argument("--threshold", type=float, default=0.75, help="Detection threshold (default: 0.75)")
        start_parser.add_argument("--cooldown", type=float, default=1.5, help="Click cooldown in seconds (default: 1.5)")
        start_parser.add_argument("--dry-run", action="store_true", help="Detect but do not click")
        start_parser.add_argument("--no-notify", dest="notify", action="store_false", help="Disable notifications")

        subparsers.add_parser("stop", help="Stop background daemon")
        subparsers.add_parser("status", help="Show current status")

        test_parser = subparsers.add_parser("test", help="Test detection on current screen")
        test_parser.add_argument("--threshold", type=float, default=0.75, help="Detection threshold (default: 0.75)")

        args = parser.parse_args()

        if not args.command:
            args.command = "run"
            args.interval = 0.35
            args.threshold = 0.75
            args.cooldown = 1.5
            args.dry_run = False
            args.notify = True

        if args.command == "run":
            monitor = AutoSubmitMonitor(
                interval=args.interval,
                threshold=args.threshold,
                cooldown=args.cooldown,
                dry_run=args.dry_run,
                notify=args.notify
            )
            monitor.run()
        elif args.command == "start":
            cmd_start(args)
        elif args.command == "stop":
            cmd_stop()
        elif args.command == "status":
            cmd_status()
        elif args.command == "test":
            test_detection(threshold=args.threshold)

    if __name__ == "__main__":
        main()
