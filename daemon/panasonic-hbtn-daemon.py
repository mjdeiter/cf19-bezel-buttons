#!/usr/bin/env python3
"""Reads raw evdev key events from the Panasonic Tablet Button device
and runs an action for each mapped key. No X/Xauthority dependency
for reading events; actions run as the logged-in user against their
live X session."""
import struct
import subprocess
import glob
import re
import sys
import os
import time

EVENT_FMT = "llHHI"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

KEY_ENTER = 28
KEY_SCREENLOCK = 152
KEY_DIRECTION = 153
KEY_KEYBOARD = 374

EV_KEY = 1

TARGET_USER = "matt"          # change to your username
DISPLAY = ":0"
OUTPUT = "LVDS1"               # change to your xrandr output name
ROTATE_ORDER = ["normal", "right", "inverted", "left"]
DEBOUNCE_SECONDS = 0.6         # guards against switch bounce on old hardware

_last_fired = {}

def find_device():
    for path in glob.glob("/sys/class/input/event*"):
        name_file = os.path.join(path, "device", "name")
        try:
            with open(name_file) as f:
                if "Tablet Button" in f.read():
                    return f"/dev/input/{os.path.basename(path)}"
        except OSError:
            continue
    return None

def find_xauthority():
    """Locate the Xauthority file for DISPLAY by inspecting a running
    process's environment -- avoids hardcoding a path that may differ
    per display manager (sddm/lightdm/startx all do this differently)."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/environ", "rb") as f:
                env = f.read().split(b"\0")
            env = {kv.split(b"=", 1)[0]: kv.split(b"=", 1)[1]
                   for kv in env if b"=" in kv}
            if env.get(b"DISPLAY") == DISPLAY.encode() and b"XAUTHORITY" in env:
                return env[b"XAUTHORITY"].decode()
        except (OSError, PermissionError):
            continue
    return None

def user_env_cmd(cmd):
    xauth = find_xauthority()
    base = ["sudo", "-u", TARGET_USER, "env", f"DISPLAY={DISPLAY}"]
    if xauth:
        base.append(f"XAUTHORITY={xauth}")
    return base + cmd

def run_as_user(cmd):
    subprocess.Popen(user_env_cmd(cmd))

def current_rotation():
    try:
        out = subprocess.run(user_env_cmd(["xrandr", "--query"]),
                              capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            if line.startswith(OUTPUT) and " connected" in line:
                # xrandr omits the rotation word entirely when it's "normal";
                # it only appears (right/inverted/left) between the geometry
                # offset and the opening "(" of the reference rotation list.
                # Don't just search the whole line for "normal"/"right"/etc --
                # the reference list at the end of the line always contains
                # all four words regardless of actual current state.
                m = re.search(r'\d+x\d+\+\d+\+\d+\s*(right|inverted|left)?\s*\(', line)
                if m and m.group(1):
                    return m.group(1)
                return "normal"
    except Exception:
        pass
    return "normal"

def debounced(code):
    now = time.time()
    last = _last_fired.get(code, 0)
    _last_fired[code] = now
    return (now - last) < DEBOUNCE_SECONDS

def handle(code):
    if debounced(code):
        return
    if code == KEY_SCREENLOCK:
        run_as_user(["i3lock"])
    elif code == KEY_DIRECTION:
        cur = current_rotation()
        nxt = ROTATE_ORDER[(ROTATE_ORDER.index(cur) + 1) % len(ROTATE_ORDER)]
        run_as_user(["xrandr", "--output", OUTPUT, "--rotate", nxt])
    elif code == KEY_KEYBOARD:
        result = subprocess.run(["pgrep", "-u", TARGET_USER, "-x", "onboard"],
                                 capture_output=True)
        if result.returncode == 0:
            subprocess.run(["pkill", "-u", TARGET_USER, "-x", "onboard"])
        else:
            run_as_user(["onboard"])
    elif code == KEY_ENTER:
        pass  # already a real key event, X picks it up on its own

def main():
    dev = find_device()
    if not dev:
        sys.exit("panasonic hbtn device not found")
    with open(dev, "rb") as f:
        while True:
            data = f.read(EVENT_SIZE)
            if len(data) < EVENT_SIZE:
                continue
            _, _, etype, code, value = struct.unpack(EVENT_FMT, data)
            if etype == EV_KEY and value == 1:
                handle(code)

if __name__ == "__main__":
    main()
