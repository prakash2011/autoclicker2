# 🚀 Antigravity Auto-Submit Tool

An automated, cross-platform background tool that monitors your screen in real time for the Antigravity confirmation/permission **"Submit"** button and automatically clicks it when it appears.

Works out-of-the-box on:
- **Windows 10 / 11** (Native Win32 `SendInput`, MSS screen capture, Per-Monitor DPI aware v2, multi-monitor support)
- **Ubuntu / Linux (Wayland)** (GNOME Mutter RemoteDesktop + PipeWire screen casting)
- **Ubuntu / Linux (X11)** (MSS + X11 XTest / xdotool)

---

## 🌟 Key Features

- **Multi-Scale Button Detection**:
  - Automatically handles high-DPI scaling (100%, 125%, 150%, 175%, 200%) and window zoom levels.
  - Mask-aware template matching ignores background theme color variations (light/dark mode).
- **Native Hardware Input**:
  - **Windows**: Modern Win32 `SendInput` hardware mouse events with automatic desktop session binding (`WinSta0\Default`).
  - **Linux Wayland**: GNOME Mutter RemoteDesktop interface.
  - **Linux X11**: Direct X11 XTest fake pointer events.
- **Multi-Monitor & Target Window Filtering**:
  - Automatically spans all connected monitors (`--monitor 0`).
  - Optionally restricts monitoring to a specific window (`--window Antigravity`).
- **Asynchronous Desktop Notifications**:
  - Instant balloon/toast alerts on click without blocking the monitoring loop.
- **Anti-Spam Cooldown**:
  - Built-in debounce cooldown (default: 1.5s) prevents duplicate clicks while the modal fades.
- **Multiple Modes**:
  - Foreground live monitor (`run`).
  - Single-shot screen test without clicking (`test`).
  - Background daemon management (`start`, `stop`, `status`).

---

## ⚡ Quick Start for Windows

1. Ensure **Python 3.10+** is installed ([python.org](https://www.python.org/downloads/)) with *"Add Python to PATH"* checked.
2. Double-click **`run_windows.bat`**.
   - Automatically verifies dependencies and starts screen monitoring.
   - Press **Ctrl+C** anytime to stop.

---

## ⚡ Quick Start for Ubuntu / Linux

1. Install Python & Pip:
   ```bash
   sudo apt update && sudo apt install -y python3 python3-pip
   ```
2. Run the launcher:
   ```bash
   chmod +x run_linux.sh
   ./run_linux.sh
   ```

---

## 🛠️ CLI Usage & Options

You can run the tool directly via terminal:

```bash
# 1. Continuous screen monitor (foreground)
python auto_submit_universal.py run

# 2. Test detection on current screen without clicking (dry run)
# Saves annotated snapshot to debug_universal_test.png
python auto_submit_universal.py test

# 3. Target a specific window (e.g. only scan Antigravity)
python auto_submit_universal.py run --window "Antigravity"

# 4. Custom check interval (e.g., every 0.25 seconds)
python auto_submit_universal.py run --interval 0.25

# 5. Custom detection confidence threshold (default: 0.75)
python auto_submit_universal.py run --threshold 0.80

# 6. Specific monitor (0 = all screens combined, 1 = primary monitor)
python auto_submit_universal.py run --monitor 1
```

---

## 🔄 Background Daemon Management (Windows & Linux)

Start monitoring in the background:
```bash
python auto_submit_universal.py start
```

Check status and recent logs:
```bash
python auto_submit_universal.py status
```

Stop the background monitor:
```bash
python auto_submit_universal.py stop
```

---

## 🔄 Linux systemd User Service (Optional)

To start the monitor automatically on user login on Ubuntu/Linux:
```bash
./install_service.sh
systemctl --user enable --now antigravity-autoclicker
systemctl --user status antigravity-autoclicker
```
