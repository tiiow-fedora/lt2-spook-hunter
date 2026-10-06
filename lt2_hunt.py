"""LT2 spook-tree hunter.

Joins public Lumber Tycoon 2 servers one at a time, skips night servers, loads
save slot 2 (a tall lookout base), photographs the ground around the plots from
the plot-select screen, then goes first person on top of the base and sweeps a
full circle (level, plus a downward-tilted pass). Frames with near-black, bare
"spook" shapes are flagged; every frame is saved for review.

Usage (most people use the control panel: hunt_gui.py):
    python lt2_hunt.py                       # hunt until stopped
    python lt2_hunt.py --max 5               # stop after 5 day servers
    python lt2_hunt.py --min-age-hours 6     # only servers the age tracker has seen for 6h+
    python lt2_hunt.py --sweep-only          # no joining: level + sweep the current view
Stop immediately with F3 (global hotkey), Ctrl+C, or by creating a file named STOP next to
this script. All three release held keys/buttons first.
"""
import argparse
import ctypes
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from ctypes import wintypes

import mss
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

PLACE_ID = 13822889
FROZEN = getattr(sys, "frozen", False)  # running as the single-file .exe
HERE = os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.abspath(__file__))  # user files
RES = getattr(sys, "_MEIPASS", HERE)  # read-only reference images bundled into the .exe
CONFIG_FILE = os.path.join(HERE, "config.json")  # machine-specific settings; see config.example.json
CFG = json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else {}
DATA = os.path.join(HERE, os.environ.get("LT2_DATA") or CFG.get("data_dir") or "data")  # relative = next to this file
OUT = os.path.join(DATA, "runs")
USED_FILE = os.path.join(HERE, "used_servers.txt")
REF_SLOT2 = os.path.join(RES, "ref_slot2.png")
STOP_FILE = os.path.join(HERE, "STOP")

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
SW, SH = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
F = SW / 1456.0  # coordinates below are in the 1456x819 frame the screenshots use


# ---------------------------------------------------------------- input ----
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG))]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _mouse(flags, data=0, dx=0, dy=0):
    i = INPUT(type=0)
    i.u.mi = MOUSEINPUT(dx, dy, data, flags, 0, None)
    _send(i)


def _key(vk, scan, up, extended=True):
    i = INPUT(type=1)
    flags = (0x0001 if extended else 0) | (0x0002 if up else 0)
    i.u.ki = KEYBDINPUT(vk, scan, flags, 0, None)
    _send(i)


def move(x, y):
    # A real absolute mouse-move event (not just SetCursorPos) so Roblox registers hover.
    px, py = int(x * F), int(y * F)
    user32.SetCursorPos(px, py)
    _mouse(0x0001 | 0x8000, dx=int(px * 65535 / (SW - 1)), dy=int(py * 65535 / (SH - 1)))
    time.sleep(0.05)
    _mouse(0x0001 | 0x8000, dx=int(px * 65535 / (SW - 1)) + 1, dy=int(py * 65535 / (SH - 1)))


class SaveDialogAbort(Exception):
    """LT2's "Delete all data on this slot and replace with current progress?" box was on screen."""


def _raw_click(x, y, hover=0.25, hold=0.06):
    move(x, y)
    time.sleep(hover)
    _mouse(0x0002)
    time.sleep(hold)
    _mouse(0x0004)


def click(x, y, hover=0.25, hold=0.06):
    # Safety net: the hunter only ever LOADS. If LT2's save-overwrite confirmation is showing, no click may
    # land (its Confirm button would overwrite a save slot): press Back instead and give up on this server.
    if delete_dialog_open(grab()):
        _raw_click(785, 384)  # "Back"
        time.sleep(0.8)
        print("save-overwrite box was open: pressed Back, abandoning this server", flush=True)
        raise SaveDialogAbort()
    _raw_click(x, y, hover, hold)


def scroll(ticks):
    move(728, 410)  # wheel goes to the window under the cursor
    time.sleep(0.3)
    for _ in range(abs(ticks)):
        _mouse(0x0800, data=(120 if ticks > 0 else -120) & 0xFFFFFFFF)
        time.sleep(0.03)


def rel_mouse(dx, dy):
    _mouse(0x0001, dx=int(dx), dy=int(dy))


def hold_left(seconds):
    _key(0x25, 0x4B, False)
    time.sleep(seconds)
    _key(0x25, 0x4B, True)


def roblox_hwnd():
    """Window handle of the running Roblox player, or 0."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process RobloxPlayerBeta -ErrorAction SilentlyContinue | Select-Object -First 1).MainWindowHandle"],
        capture_output=True, text=True, creationflags=0x08000000).stdout.strip()  # no console flash
    return int(out) if out.isdigit() else 0


def focus_roblox():
    hwnd = roblox_hwnd()
    if hwnd:
        user32.keybd_event(0x12, 0, 0, 0)  # alt trick so SetForegroundWindow is allowed
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)
    time.sleep(0.4)


def setup_report():
    """Passive checks for the "Test my setup" button: looks only, never clicks.
    Returns [(ok, message)] where ok is True, False (a problem), or None (just information)."""
    r = []
    ok = abs(SW / SH - 16 / 9) < 0.02
    r.append((ok, f"Main monitor is {SW}x{SH}" + ("" if ok else ": it must be 16:9, e.g. 1920x1080")))
    hwnd = roblox_hwnd()
    if not hwnd:
        r.append((False, "Roblox isn't running. Open Roblox and join any Lumber Tycoon 2 server."))
        return r
    rc, pt = wintypes.RECT(), wintypes.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    x, y, w, h = pt.x, pt.y, rc.right, rc.bottom
    if abs(x) <= 2 and abs(y) <= 2 and abs(w - SW) <= 4 and abs(h - SH) <= 4:
        r.append((True, "Roblox fills the main monitor"))
    elif user32.IsIconic(hwnd):
        r.append((False, "Roblox is minimized. Open it on the main monitor and press F11 (fullscreen)."))
    elif abs(x) <= 10 and 0 <= y <= 60 and abs(w - SW) <= 20:
        r.append((False, "Roblox is maximized but windowed (title bar on top). Press F11 for fullscreen."))
    else:
        r.append((False, f"Roblox's window is {w}x{h} at ({x}, {y}). Move it to the main monitor and press F11."))
    img = grab()
    if menu_visible(img):
        r.append((True, "Lumber Tycoon 2 is loaded (its Menu button is on screen)"))
        r.append((None, "It's daytime in this server" if is_day(img) else
                  "It's night in this server (fine: the hunter skips night servers)"))
    else:
        r.append((False, "Can't see Lumber Tycoon 2's Menu button. Join an LT2 server, close any open menus, "
                         "and keep Roblox in front."))
    try:
        os.makedirs(DATA, exist_ok=True)
        free = shutil.disk_usage(DATA).free / 1e9
        r.append((free > 5, f"Pictures go to {DATA} ({free:.0f} GB free)" +
                  ("" if free > 5 else ": low on space, set data_dir in config.json to a bigger drive")))
    except OSError as e:
        r.append((False, f"Can't write to the data folder {DATA}: {e}"))
    try:
        hrs = read_alive().get("tracking_hours", 0)
        r.append((None, f"Age tracker is working ({hrs:.1f} h of history)"))
    except Exception:
        r.append((None, "Age tracker not set up (optional: lets you hunt only old servers)"))
    return r


# ------------------------------------------------------------- emergency stop ----
STOP_VK = (0x72, 0x13)  # F3 (and Pause/Break)


def release_all():
    """Let go of everything the script may be holding (arrow key, mouse buttons, alt)."""
    for vk, scan in ((0x25, 0x4B), (0x27, 0x4D), (0x26, 0x48), (0x28, 0x50)):
        _key(vk, scan, True)
    _mouse(0x0004)  # left up
    _mouse(0x0010)  # right up
    user32.keybd_event(0x12, 0, 2, 0)  # alt up


def _hard_stop(why):
    release_all()
    print(f"stopped by {why}", flush=True)
    os._exit(0)


def _watch_stop():
    while True:
        if any(user32.GetAsyncKeyState(k) & 0x8000 for k in STOP_VK):
            _hard_stop("hotkey (F3)")
        if os.path.exists(STOP_FILE):
            _hard_stop("STOP file")
        time.sleep(0.03)


def start_stop_watcher():
    threading.Thread(target=_watch_stop, daemon=True).start()


# --------------------------------------------------------------- vision ----
_sct = mss.MSS()
PRIMARY = {"left": 0, "top": 0, "width": SW, "height": SH}  # Roblox runs on the primary display


def grab():
    shot = _sct.grab(PRIMARY)
    return Image.frombytes("RGB", shot.size, shot.rgb)


def region(img, x0, y0, x1, y1):
    return np.asarray(img.crop((int(x0 * F), int(y0 * F), int(x1 * F), int(y1 * F))), dtype=np.float32)


def luma(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def is_day(img):
    # Bright sky-blue pixels anywhere across the upper side strips (a tree or sign
    # can block any one patch, but not all of the sky). Night sky is dark, luma < 60.
    n_blue, n_all = 0, 0
    for x0, x1 in ((150, 420), (1040, 1456)):
        a = region(img, x0, 25, x1, 260)
        r, b = a[..., 0], a[..., 2]
        n_blue += int(((b > r + 15) & (luma(a) > 110)).sum())
        n_all += r.size
    if n_blue / n_all > 0.02:
        return True
    # Sky fully hidden by trees: fall back to the grass, ~60 luma by day, ~20 at night.
    return float(np.median(luma(region(img, 100, 560, 1356, 790)))) > 34  # night <= 28, day >= 37 (measured)


def menu_visible(img):  # LT2's white "Menu" button, top centre, only exists once the game has loaded
    a = region(img, 705, 5, 750, 25)
    return (a.min(axis=2) > 225).mean() > 0.3  # button is ~55% white; sky/terrain ~0%


def popup_open(img):  # white dialog with black text averages ~220 vs ~35 for plain world
    a = luma(region(img, 640, 340, 830, 400))
    return a.mean() > 150 and (a < 90).mean() > 0.03  # dark text pixels rule out a plain bright sky


def select_btn_visible(img):
    return luma(region(img, 90, 768, 185, 790)).mean() > 150


def confirm_dialog_open(img):
    return luma(region(img, 620, 330, 840, 370)).mean() > 150


REF_DELETE = os.path.join(RES, "ref_delete_dialog.png")
_ref_delete = None


def delete_dialog_open(img):
    """True when the 'Delete all data on this slot and replace with current progress?' box is up."""
    global _ref_delete
    if _ref_delete is None:
        _ref_delete = Image.open(REF_DELETE).convert("RGB")
    crop = img.crop((int(623 * F), int(302 * F), int(834 * F), int(320 * F))).resize(_ref_delete.size)
    diff = np.abs(np.asarray(crop.convert("RGB"), dtype=np.float32) - np.asarray(_ref_delete, dtype=np.float32))
    return diff.mean() < 25


_ref_slot2 = None


def slot2_panel_shown(img):
    global _ref_slot2
    if _ref_slot2 is None:
        _ref_slot2 = Image.open(REF_SLOT2).convert("RGB")
    crop = img.crop((int(610 * F), int(318 * F), int(690 * F), int(342 * F))).resize(_ref_slot2.size)
    diff = np.abs(np.asarray(crop.convert("RGB"), dtype=np.float32) - np.asarray(_ref_slot2, dtype=np.float32))
    return diff.mean() < 20


def tower_visible(img):
    a = region(img, 0, 0, 1456, 819)
    blue = (a[..., 2] > 200) & (a[..., 0] < 70) & (a[..., 1] < 70)
    return blue.mean() > 0.004


def changed(before, after, box, thresh=10):
    a, b = region(before, *box), region(after, *box)
    return np.abs(a - b).mean() > thresh


def wait_for(pred, timeout, step=0.2):
    end = time.time() + timeout
    while time.time() < end:
        if pred(grab()):
            return True
        time.sleep(step)
    return False


def click_until(x, y, pred, tries=5, settle=2.0, hover=0.25):
    for _ in range(tries):
        click(x, y, hover=hover)
        if wait_for(pred, settle, step=0.15):  # continue the moment it worked
            return True
    return False


def click_until_change(x, y, box, tries=5, settle=2.0):
    for _ in range(tries):
        before = grab()
        click(x, y)
        if wait_for(lambda im: changed(before, im, box), settle, step=0.15):
            return True
    return False


# ------------------------------------------------------------- servers ----
def fetch_servers():
    url = (f"https://games.roblox.com/v1/games/{PLACE_ID}/servers/Public"
           "?sortOrder=Asc&limit=100")
    with urllib.request.urlopen(url, timeout=20) as r:
        data = json.load(r)["data"]
    return [s["id"] for s in data if s["playing"] < s["maxPlayers"]]


def used_servers():
    if not os.path.exists(USED_FILE):
        return set()
    return set(open(USED_FILE).read().split())


_pool = []  # fetched once and worked through; the list API rate-limits (HTTP 429)

MIN_AGE_HOURS = 0.0


def read_alive():
    """alive.json from the optional server-age tracker (tracker/lt2_tracker.py), per config.json:
    {"tracker": {"file": "path/to/alive.json"}} when it runs on this PC, or
    {"tracker": {"ssh": ["ssh", "user@host"], "alive_path": "/path/to/alive.json"}} when it runs elsewhere."""
    t = CFG.get("tracker") or {}
    if t.get("file"):
        with open(os.path.join(HERE, t["file"])) as f:
            return json.load(f)
    if t.get("ssh"):
        out = subprocess.run(list(t["ssh"]) + ["cat", t["alive_path"]], capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout)
    raise RuntimeError("no tracker configured in config.json")


def old_servers(min_age):
    """Joinable server ids the tracker has seen for >= min_age hours, oldest first.

    Returns (ids, tracking_hours); ids is [] if none qualify yet or the tracker can't be read.
    """
    try:
        data = read_alive()
    except Exception as e:
        print("could not read the server-age tracker:", e)
        return [], 0.0
    used = used_servers()
    ids = [s["id"] for s in data["servers"]
           if s["age_hours_min"] >= min_age and (s.get("playing") or 0) < (s.get("max") or 6)
           and s["id"] not in used]
    return ids, data.get("tracking_hours", 0.0)


def tracker_age(sid):
    """Lower-bound age in hours of a server per the tracker, or None if unknown."""
    try:
        for srv in read_alive()["servers"]:
            if srv["id"] == sid:
                return srv["age_hours_min"]
    except Exception:
        pass
    return None


def next_server():
    global _pool
    if MIN_AGE_HOURS > 0:
        while True:  # wait for the tracker (refreshes every 10 min) instead of quitting
            ids, tracked = old_servers(MIN_AGE_HOURS)
            if ids:
                break
            print(f"waiting: no unused servers >= {MIN_AGE_HOURS}h old yet (tracker has {tracked}h of history); "
                  "rechecking in 5 min", flush=True)
            time.sleep(300)
        sid = ids[0]  # oldest first
        with open(USED_FILE, "a") as f:
            f.write(sid + "\n")
        return sid
    for attempt in range(6):
        used = used_servers()
        _pool = [s for s in _pool if s not in used]
        if not _pool:
            try:
                _pool = [s for s in fetch_servers() if s not in used]
                random.shuffle(_pool)
            except Exception as e:
                # Roblox's list API rate-limits (HTTP 429): fall back to the TrueNAS tracker's copy of the list.
                ids, _tracked = old_servers(0)
                if ids:
                    print(f"server list failed ({e}); using the tracker's list ({len(ids)} servers)", flush=True)
                    _pool = ids
                    random.shuffle(_pool)
                else:
                    wait = 60 * (attempt + 1)
                    print(f"server list failed ({e}) and the tracker list is unavailable; retrying in {wait}s")
                    time.sleep(wait)
                    continue
        if _pool:
            sid = _pool.pop()
            with open(USED_FILE, "a") as f:
                f.write(sid + "\n")
            return sid
        time.sleep(15)
    return None


def join(sid):
    os.startfile(f"roblox://experiences/start?placeId={PLACE_ID}&gameInstanceId={sid}")


# ----------------------------------------------------------- game steps ----
LOAD_COOLDOWN = 62  # LT2: "You may only load once every 60 seconds"
_last_load = 0.0


def close_popups():
    """Dismiss LT2 dialogs: the welcome box has its button at y~496, the load-cooldown box at y~452."""
    for pos in ((785, 452), (784, 496), (785, 452)):
        if not popup_open(grab()):
            return
        click(*pos)
        time.sleep(0.6)


def wait_load_cooldown():
    left = LOAD_COOLDOWN - (time.time() - _last_load)
    if left > 0:
        print(f"waiting {left:.0f}s for the load cooldown", flush=True)
        time.sleep(left)


def load_slot2(tag, arrows=0, stop_at_plot=False, on_plot_screen=None):
    """Returns True once the tower base is loaded. `arrows` clicks the plot-select > arrow that many
    times first (the server has 9 plots, so it cycles through them), putting the tower on another plot."""
    global _last_load
    focus_roblox()
    scroll(-45)  # a reload happens from first person, where the mouse is locked and UI clicks are ignored
    time.sleep(1.0)
    wait_load_cooldown()
    close_popups()
    if not click_until_change(726, 16, (600, 280, 860, 520)):  # LT2 Menu
        print("menu did not open")
        return False
    if not click_until_change(668, 360, (520, 190, 940, 640)):  # Load
        print("load list did not open")
        return False
    if os.path.exists(REF_SLOT2):
        # Success = the panel title reads "Slot 2" (never just "something changed",
        # which also fires mid-animation). Retry the row click until it matches.
        if not click_until(584, 292, slot2_panel_shown, tries=4, settle=2.0):
            # Wrong slot, a cooldown box, or a lag spike. Do NOT click around in the save UI to recover
            # (a stray click once opened another slot's save panel): give up on this server; leaving it
            # clears every open dialog.
            print("slot 2 panel never showed; leaving this server untouched")
            return False
    elif not click_until_change(584, 292, (580, 300, 870, 400)):
        print("slot panel did not open")
        return False
    grab().crop((int(610 * F), int(318 * F), int(690 * F), int(342 * F))).save(
        os.path.join(OUT, f"{tag}_slotpanel.png"))
    before = grab()
    _last_load = time.time()
    click(656, 374)  # Load slot
    if not wait_for(lambda im: changed(before, im, (560, 380, 900, 440)), 3.0, step=0.15):
        click(656, 374)
    if not wait_for(select_btn_visible, 45):
        print("plot screen never appeared")
        return False
    close_popups()
    if stop_at_plot:
        return True
    if on_plot_screen:
        on_plot_screen()
    for _ in range(arrows):
        click(807, 739, hover=0.15)
        time.sleep(0.5)
    if not click_until(136, 779, confirm_dialog_open, tries=6, settle=2.5):
        print("confirm dialog never appeared")
        return False
    for _ in range(6):
        click(670, 424)
        if wait_for(lambda im: not confirm_dialog_open(im), 3.0, step=0.15):
            break
    # Loaded = out of the plot screen and the in-game Menu button is back (the blue tower base is only in
    # view when the spawn happens to face it, which depends on the plot).
    if not wait_for(lambda im: menu_visible(im) and not select_btn_visible(im), 45):
        print("never got back into the game after Select", flush=True)
        return False
    # The Menu button comes back BEFORE LT2 finishes loading the base and moves you onto it. Wait for the
    # tower's blue base to come into view; if the spawn faces elsewhere, at_ground_level() catches it later.
    if not wait_for(tower_visible, 30):
        print("tower base not seen yet; continuing (the first sweep checks the height)", flush=True)
    time.sleep(2.0)
    return True


def level_camera():
    scroll(45)
    time.sleep(1.5)
    # Relative mouse deltas drive the first-person camera (~0.3 degrees per px,
    # steps under ~4 px are ignored): slam the view straight down, then ease up.
    move(728, 410)
    time.sleep(0.3)
    rel_mouse(0, 500)
    time.sleep(0.4)
    best = None
    for _ in range(45):
        rel_mouse(0, -8)
        time.sleep(0.15)
        a = region(grab(), 400, 0, 1056, 819)
        r, g, b = a[..., 0], a[..., 1], a[..., 2]
        sky = (b > r + 25) & (luma(a) > 150)
        rows = np.where(sky.mean(axis=1) > 0.5)[0]
        horizon = (rows.max() / a.shape[0]) if len(rows) else 0.0
        best = horizon
        if 0.50 <= horizon <= 0.62:
            return True
    print("could not level camera, horizon at", best)
    return False


def find_trees(img, black_lum=50, thin_lum=75, sat_max=16, min_area=6, thin_size=9, thin_contrast=50, min_mean=100, mask_hud=True):
    """Spook-tree candidates at 480x270 working size. Returns (score, boxes in full-res px).

    Rule A: near-black neutral blobs of any shape. Daytime scenery is never this dark, so
            black bark stands out (0 false alarms on ~300 saved frames; every pasted black
            test tree was found).
    Rule B: thin dark neutral features, much darker than their surroundings (black top-hat),
            for trees hazed toward gray by distance. Looser, so it false-alarms on shaded
            cliff edges now and then; the contrast knob trades misses against false alarms.
    Score is -1 for a dim frame (night / dusk / black screen; daytime frames are 135+).
    """
    a = np.asarray(img.convert("RGB").resize((480, 270)), dtype=np.float32)
    mx, mn = a.max(axis=2), a.min(axis=2)
    l = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
    if l[30:225].mean() < min_mean:
        return -1, []
    neutral = (mx - mn) < sat_max
    rule_a = neutral & (l < black_lum)
    blackhat = ndimage.grey_closing(l, size=(thin_size, thin_size)) - l
    rule_b = neutral & (blackhat > thin_contrast) & (l < thin_lum)
    m = rule_a | rule_b
    if mask_hud:
        m[:30, :] = False       # top HUD
        m[-45:, :] = False      # hotbar / tower
        m[:115, :135] = False   # chat panel (it pops open now and then)
    m = ndimage.binary_closing(m, structure=np.ones((2, 2)))
    lab, _ = ndimage.label(m, structure=np.ones((3, 3)))
    k = img.size[0] / 480.0
    best, boxes = 0, []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        area = int((lab[sl] == i).sum())
        if area >= min_area and sl[0].stop - sl[0].start >= 3:
            best = max(best, area)
            boxes.append((int(sl[1].start * k), int(sl[0].start * k), int(sl[1].stop * k), int(sl[0].stop * k), area))
    return best, boxes


def dark_score(img):
    return find_trees(img)[0]


def horizon_fraction(img):
    a = region(img, 400, 0, 1056, 819)
    r, b = a[..., 0], a[..., 2]
    sky = (b > r + 25) & (luma(a) > 150)
    rows = np.where(sky.mean(axis=1) > 0.5)[0]
    return (rows.max() / a.shape[0]) if len(rows) else 0.0


def nudge_level(lo=0.47, hi=0.66):
    """Pitch drifts a little during a sweep, so re-aim at the horizon before each frame."""
    for _ in range(6):
        h = horizon_fraction(grab())
        if lo <= h <= hi:
            return
        rel_mouse(0, -8 if h < lo else 8)
        time.sleep(0.3)


def tilt_down(px):
    """Pitch the first-person camera down by relative mouse steps (steps under ~4 px are ignored)."""
    for _ in range(max(px // 8, 0)):
        rel_mouse(0, 8)
        time.sleep(0.1)
    time.sleep(0.3)


def sweep(folder, steps=10, start=0, pitch_px=0):
    """Turn a full circle taking `steps` frames, saved as <start+i>.jpg. pitch_px > 0 looks down at the
    ground by that many mouse pixels (~0.3 degrees each) instead of re-levelling on the horizon."""
    os.makedirs(folder, exist_ok=True)
    scores, crops = [], []
    if pitch_px:
        nudge_level()
        tilt_down(pitch_px)
    for i in range(steps):
        time.sleep(0.4)
        if not pitch_px:
            nudge_level()
        time.sleep(0.2)
        img = grab()
        idx = start + i
        img.save(os.path.join(folder, f"{idx:02d}.jpg"), quality=88)
        score, boxes = find_trees_tiled(img)
        scores.append(score)
        if score > 0:  # keep padded crops of the flagged spots for a quick review
            for x0, y0, x1, y1, _area in sorted(boxes, key=lambda b: -b[4])[:4]:
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                crop = img.crop((max(cx - 90, 0), max(cy - 90, 0), min(cx + 90, img.size[0]), min(cy + 90, img.size[1])))
                crops.append((idx, crop.resize((240, 240))))
        if len(scores) >= 2 and scores[-1] < 0 and scores[-2] < 0:
            break  # night fell mid-sweep; the rest would be unusable
        hold_left(0.3)
    if crops:  # one small image per flagged server: crops of every flagged spot, frame number noted
        _save_crops(folder, crops, start)
    return scores


def find_trees_tiled(img):
    """find_trees on four half-size tiles, so far-off features keep twice the resolution (the swamp is far away).
    HUD zones are masked on the full frame afterwards."""
    w, h = img.size
    best, boxes = 0, []
    small = np.asarray(img.convert("L").resize((480, 270)), dtype=np.float32)
    if small[30:225].mean() < 80:  # whole frame dim = night (a tile of dark ground alone must not count)
        return -1, []
    for ty in (0, h // 2):
        for tx in (0, w // 2):
            sc, bx = find_trees(img.crop((tx, ty, tx + w // 2, ty + h // 2)), mask_hud=False, min_mean=60)
            if sc < 0:
                continue  # a tile of dark ground on its own: nothing to see, and it only makes noise
            for x0, y0, x1, y1, area in bx:
                x0, x1, y0, y1 = x0 + tx, x1 + tx, y0 + ty, y1 + ty
                cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
                if cy < 30 / 270 or cy > 1 - 45 / 270 or (cy < 115 / 270 and cx < 135 / 480):
                    continue  # top HUD, hotbar, chat panel
                boxes.append((x0, y0, x1, y1, area))
                best = max(best, area)
    return best, boxes


def hold_right(seconds):
    _key(0x27, 0x4D, False)
    time.sleep(seconds)
    _key(0x27, 0x4D, True)


REF_HEADING = os.path.join(HERE, "ref_heading.jpg")


def heading_matches(frame0_path, thresh=0.7):
    """The swamp pass is aimed by heading, so check frame 0 looks like the usual spawn view (cliffs, village,
    volcano in the usual place). Weak check (similar scenes correlate too): it only catches a clearly different view."""
    try:
        def small(img):
            a = np.asarray(img.convert("L").resize((96, 54)), dtype=np.float32)[6:44]
            return (a - a.mean()) / (a.std() + 1e-6)
        return float((small(Image.open(frame0_path)) * small(Image.open(REF_HEADING))).mean()) >= thresh
    except OSError:
        return True


def swamp_pass(folder, start):
    """The swamp (blue crescent pond in the cliffs) sits between the first two frames of the level sweep.
    Starting back at that heading: 3 headings x 3 downward tilts, checked with the tiled detector."""
    nudge_level()
    scores, idx = [], start
    for tilt in (0, 24, 48):
        if tilt:
            tilt_down(24)
        for k in range(3):
            time.sleep(0.5)
            img = grab()
            img.save(os.path.join(folder, f"{idx:02d}.jpg"), quality=90)
            scores.append(find_trees_tiled(img)[0])
            idx += 1
            if k < 2:
                hold_left(0.15)
        hold_right(0.3)
    for _ in range(6):  # tilt back up
        rel_mouse(0, -8)
        time.sleep(0.1)
    return scores


def _save_crops(folder, crops, start):
    crops = crops[:16]
    cw = 4
    cs = Image.new("RGB", (cw * 240, ((len(crops) + cw - 1) // cw) * 240))
    for n, (fi, c) in enumerate(crops):
        ImageDraw.Draw(c).text((6, 6), f"f{fi:02d}", fill=(255, 255, 0))
        cs.paste(c, ((n % cw) * 240, (n // cw) * 240))
    cs.save(os.path.join(folder, "cands.jpg" if start == 0 else f"cands_{start}.jpg"), quality=88)


def make_sheet(folder):
    """Contact sheet of every numbered frame in the folder."""
    names = sorted(n for n in os.listdir(folder) if re.fullmatch(r"\d\d\.jpg", n))
    cols, w, h = 4, 640, 360
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, max(rows, 1) * h))
    for i, n in enumerate(names):
        sheet.paste(Image.open(os.path.join(folder, n)).resize((w, h)), ((i % cols) * w, (i // cols) * h))
    sheet.save(os.path.join(folder, "sheet.jpg"), quality=85)


PLOT_BLACK_LUM = 20  # plot-select view is vignetted dark (mean luma ~60): only near-black counts as a candidate


def plot_screen_survey(tag, sid, args, plots=3, frames_per=4):
    """At the plot-select screen the camera orbits the chosen plot at ground level. Click through every plot,
    grabbing a few frames of each orbit, so the land around the tower gets a ground-level look."""
    folder = os.path.join(OUT, tag)
    os.makedirs(folder, exist_ok=True)
    scores = []
    for _p in range(plots):
        for _k in range(frames_per):
            time.sleep(1.1)
            img = grab()
            img.save(os.path.join(folder, f"{len(scores):02d}.jpg"), quality=88)
            scores.append(find_trees(img, black_lum=PLOT_BLACK_LUM, thin_lum=0, min_mean=30)[0])
        click(807, 739, hover=0.12)  # next plot (the camera re-centres and keeps orbiting it)
        time.sleep(0.8)
    for _p in range(plots):  # back to the plot we started on, so the spawn heading stays the usual one
        click(648, 739, hover=0.12)
        time.sleep(0.5)
    make_sheet(folder)
    flagged = [i for i, sc in enumerate(scores) if sc >= args.threshold]
    print(f"[{tag}] plot-screen survey scores={scores} flagged={flagged}", flush=True)
    with open(os.path.join(OUT, "log.txt"), "a") as f:
        f.write(f"{tag} {sid} scores={scores} flagged={flagged}\n")
    with open(os.path.join(folder, "meta.json"), "w") as f:
        json.dump({"sid": sid, "ts": time.time(), "age_hours_min": tracker_age(sid), "scores": scores,
                   "flagged": flagged, "kind": "plot_screen"}, f)
    if flagged:
        open(os.path.join(folder, "FLAGGED"), "w").write(str(flagged))


def at_ground_level(folder, n=10):
    """True if the level sweep was taken standing on the grass (the base never loaded / no teleport):
    measured median grass cover of the lower frame is <= 0.01 from a tower and ~0.5 on the ground."""
    fr = []
    for i in range(n):
        p = os.path.join(folder, f"{i:02d}.jpg")
        if os.path.exists(p):
            a = np.asarray(Image.open(p).convert("RGB").resize((480, 270)), dtype=np.float32)[150:240]
            r, g, b = a[..., 0], a[..., 1], a[..., 2]
            l = 0.299 * r + 0.587 * g + 0.114 * b
            fr.append(float(((g > r + 12) & (g > b) & (l > 20) & (l < 95)).mean()))
    return bool(fr) and float(np.median(fr)) > 0.2


def scan_plot(tag, sid, arrows, args, survey=False):
    """Load slot 2 onto the plot `arrows` clicks along, sweep, log. Returns True if usable frames were saved."""
    if not is_day(grab()):  # re-check just before loading: night can fall after the join-time check
        print(f"[{tag}] night before loading, skipping", flush=True)
        return False
    hook = (lambda: plot_screen_survey(tag + "g", sid, args, plots=args.survey_plots)) if survey else None
    if not load_slot2(tag, arrows=arrows, on_plot_screen=hook):
        print(f"[{tag}] load failed, skipping")
        return False
    if not level_camera():
        print(f"[{tag}] leveling uncertain, sweeping anyway")
    if luma(region(grab(), 0, 100, 1456, 700)).mean() < 60:
        print(f"[{tag}] too dark after loading (night fell), skipping")
        return False
    folder = os.path.join(OUT, tag)
    scores = sweep(folder)
    if at_ground_level(folder):
        print(f"[{tag}] sweep was taken on the ground, not on the base (didn't load in time?), discarding",
              flush=True)
        return False
    if args.swamp_pass and scores and scores[-1] >= 0:
        if heading_matches(os.path.join(folder, "00.jpg")):
            scores += swamp_pass(folder, len(scores))
        else:
            print(f"[{tag}] spawn heading looks different; skipping the swamp pass", flush=True)
    for px in [int(x) for x in args.ground_passes.split(",") if x.strip()]:
        if scores and scores[-1] < 0:
            break  # night fell; more frames are useless
        scores += sweep(folder, 10, start=len(scores), pitch_px=px)
    make_sheet(folder)
    if np.mean([s < 0 for s in scores]) > 0.5:
        print(f"[{tag}] sweep was black/dark, discarding")
        return False
    flagged = [i for i, s in enumerate(scores) if s >= args.threshold]
    print(f"[{tag}] scores={scores} flagged={flagged}")
    with open(os.path.join(OUT, "log.txt"), "a") as f:
        f.write(f"{tag} {sid} scores={scores} flagged={flagged}\n")
    with open(os.path.join(folder, "meta.json"), "w") as f:
        json.dump({"sid": sid, "ts": time.time(), "age_hours_min": tracker_age(sid),
                   "scores": scores, "flagged": flagged, "plot_arrows": arrows}, f)
    if flagged:
        open(os.path.join(folder, "FLAGGED"), "w").write(str(flagged))
    return True


# ------------------------------------------------------------------ main ----
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--sweep-only", action="store_true")
    ap.add_argument("--threshold", type=int, default=6)
    ap.add_argument("--ground-passes", default="40",
                    help="comma list of extra downward-tilt sweeps in mouse px (~0.3 deg each); '' for none")
    ap.add_argument("--survey-plots", type=int, default=3, help="how many plots the plot-select survey looks at")
    ap.add_argument("--no-plot-survey", dest="plot_survey", action="store_false",
                    help="skip the ground-level orbit survey at the plot-select screen")
    ap.add_argument("--no-swamp-pass", dest="swamp_pass", action="store_false",
                    default=bool(CFG.get("swamp_pass", False)),
                    help="skip the close-up pass aimed at the swamp (on only if config.json sets swamp_pass)")
    ap.add_argument("--plot-offsets", default="0",
                    help="comma list: for each, reload slot 2 with that many plot-select > clicks and sweep again")
    ap.add_argument("--test-plot", type=int, default=-1,
                    help="load slot 2 with this many plot arrow clicks, sweep, save to runs/plot_test")
    ap.add_argument("--plot-screen", action="store_true", help="load slot 2 up to the plot-select screen and stop")
    ap.add_argument("--min-age-hours", type=float, default=0.0,
                    help="only join servers the age tracker has seen for at least this long (try 6-9)")
    args = ap.parse_args()
    global MIN_AGE_HOURS
    MIN_AGE_HOURS = args.min_age_hours
    os.makedirs(OUT, exist_ok=True)
    if os.path.exists(STOP_FILE):
        print("STOP file exists; delete it to run:", STOP_FILE)
        return
    start_stop_watcher()
    print("running; press F3 to stop immediately", flush=True)

    if args.plot_screen:
        focus_roblox()
        print("at plot screen:", load_slot2("plotscreen", stop_at_plot=True))
        return

    if args.test_plot >= 0:
        focus_roblox()
        print("load:", load_slot2("plottest", arrows=args.test_plot))
        level_camera()
        fol = os.path.join(OUT, "plot_test")
        sc = sweep(fol)
        make_sheet(fol)
        print("scores", sc)
        return

    if args.sweep_only:
        focus_roblox()
        level_camera()
        fol = os.path.join(OUT, "sweep_only")
        sc = sweep(fol)
        for px in [int(x) for x in args.ground_passes.split(",") if x.strip()]:
            sc += sweep(fol, 10, start=len(sc), pitch_px=px)
        make_sheet(fol)
        print("scores", sc)
        return

    offsets = [int(x) for x in args.plot_offsets.split(",") if x.strip()] or [0]
    done = 0
    while True:
        sid = next_server()
        if not sid:
            print("no servers left")
            break
        tag = time.strftime("%H%M%S") + "_" + sid[:8]
        print(f"[{tag}] joining")
        was_in_game = menu_visible(grab())
        join(sid)
        # A real join leaves the old game first (Menu button vanishes), then loads the new
        # one. If the old game never goes away the join failed (server gone or full).
        if was_in_game and not wait_for(lambda im: not menu_visible(im), 25, step=0.2):
            print(f"[{tag}] join failed (server gone or full?), skipping")
            continue
        if not wait_for(menu_visible, 70, step=0.5):
            print(f"[{tag}] game never finished loading, skipping")
            continue
        time.sleep(3)  # let the welcome popup and lighting settle
        shot = grab()
        if not is_day(shot):
            shot.resize((960, 540)).save(os.path.join(OUT, f"{tag}_NIGHT.jpg"), quality=80)
            print(f"[{tag}] night, skipping")
            continue
        counted = False
        for n, off in enumerate(offsets):
            ptag = tag if n == 0 else f"{tag}p{off}"  # extra plots are logged as their own entries
            try:
                if scan_plot(ptag, sid, off, args, survey=(n == 0 and args.plot_survey)):
                    counted = True
            except SaveDialogAbort:
                break  # Back was pressed; joining the next server clears whatever was open
        if not counted:
            continue
        done += 1
        if args.max and done >= args.max:
            break
    print("finished", done, "day servers")


def cli():
    try:
        main()
    except KeyboardInterrupt:
        release_all()
        print("stopped by Ctrl+C")


if __name__ == "__main__":
    cli()
