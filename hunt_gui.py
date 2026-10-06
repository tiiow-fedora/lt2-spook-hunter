"""LT2 spook hunt control panel: Start/Stop the hunter, watch progress, join flagged servers.

Double-click "LT2 Spook Hunt" on the desktop (or run: pythonw hunt_gui.py).
"""
import json
import os
import re
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(HERE, "config.json")  # machine-specific settings; see config.example.json
CFG = json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else {}
DATA = os.path.join(HERE, os.environ.get("LT2_DATA") or CFG.get("data_dir") or "data")  # relative = next to this file
RUNS = os.path.join(DATA, "runs")
STOP_FILE = os.path.join(HERE, "STOP")
REVIEWED = os.path.join(HERE, "reviewed.txt")
STDOUT = os.path.join(RUNS, "hunt_stdout.txt")
PLACE_ID = 13822889
PY = sys.executable.replace("pythonw.exe", "python.exe")


def join_link(sid):
    return f"roblox://experiences/start?placeId={PLACE_ID}&gameInstanceId={sid}"


def ago(ts):
    s = int(time.time() - ts)
    if s < 90:
        return f"{s}s ago"
    if s < 5400:
        return f"{s // 60} min ago"
    return f"{s / 3600:.1f} h ago"


def read_log():
    """{tag: (sid, scores, flagged)} from runs/log.txt."""
    out = {}
    try:
        for line in open(os.path.join(RUNS, "log.txt"), encoding="utf-8"):
            m = re.match(r"(\S+) (\S+) scores=\[(.*?)\] flagged=\[(.*?)\]", line)
            if m:
                scores = [int(x) for x in m.group(3).split(",") if x.strip()]
                flagged = [int(x) for x in m.group(4).split(",") if x.strip()]
                out[m.group(1)] = (m.group(2), scores, flagged)
    except OSError:
        pass
    return out


def reviewed():
    try:
        return set(open(REVIEWED).read().split())
    except OSError:
        return set()


def make_marked(tag, frames):
    """Montage of the flagged frames with red boxes where the detector sees dark trees."""
    from PIL import Image, ImageDraw
    import lt2_hunt  # find_trees; importing does not start anything
    folder = os.path.join(RUNS, tag)
    try:
        plot_screen = json.load(open(os.path.join(folder, "meta.json"))).get("kind") == "plot_screen"
    except (OSError, ValueError):
        plot_screen = False
    tiles = []
    for i in frames:
        img = Image.open(os.path.join(folder, f"{i:02d}.jpg")).convert("RGB")
        if plot_screen:  # same settings the hunter used on the dark plot-select frames
            _score, boxes = lt2_hunt.find_trees(img, black_lum=lt2_hunt.PLOT_BLACK_LUM, thin_lum=0, min_mean=30)
        else:
            _score, boxes = lt2_hunt.find_trees_tiled(img)
        d = ImageDraw.Draw(img)
        for x0, y0, x1, y1, area in boxes:
            d.rectangle((x0 - 14, y0 - 14, x1 + 14, y1 + 14), outline=(255, 0, 0), width=4)
            d.text((x0 - 12, max(y0 - 28, 0)), str(area), fill=(255, 255, 0))
        d.text((8, 8), f"frame {i}", fill=(255, 255, 0))
        tiles.append(img.resize((960, 540)))
    cols = 1 if len(tiles) == 1 else 2
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 960, rows * 540))
    for n, t in enumerate(tiles):
        sheet.paste(t, ((n % cols) * 960, (n // cols) * 540))
    out = os.path.join(folder, "marked.jpg")
    sheet.save(out, quality=88)
    return out


def save_samples(tag, frames, label):
    """File the flagged frames + padded crops of each box under dataset/<label>/ for detector tuning."""
    from PIL import Image
    import lt2_hunt
    out = os.path.join(DATA, "dataset", label)
    os.makedirs(out, exist_ok=True)
    for i in frames:
        p = os.path.join(RUNS, tag, f"{i:02d}.jpg")
        if not os.path.exists(p):
            continue
        img = Image.open(p).convert("RGB")
        img.save(os.path.join(out, f"{tag}_f{i:02d}.jpg"), quality=92)
        for n, (x0, y0, x1, y1, area) in enumerate(lt2_hunt.find_trees(img)[1]):
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            img.crop((max(cx - 100, 0), max(cy - 100, 0), cx + 100, cy + 100)).save(
                os.path.join(out, f"{tag}_f{i:02d}_b{n}.png"))


class App:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.rows = {}  # tree iid -> dict
        root.title("LT2 Spook Hunt")
        root.geometry("900x560")

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        self.btn = ttk.Button(top, text="Start hunt", command=self.toggle, width=14)
        self.btn.pack(side="left")
        ttk.Label(top, text="  Only servers older than (h):").pack(side="left")
        self.age = tk.StringVar(value="0")
        ttk.Spinbox(top, from_=0, to=24, width=4, textvariable=self.age).pack(side="left")
        ttk.Label(top, text="  Max servers:").pack(side="left")
        self.maxn = tk.StringVar(value="25")
        self.maxbox = ttk.Spinbox(top, from_=1, to=500, width=5, textvariable=self.maxn)
        self.maxbox.pack(side="left")
        self.inf = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="Infinite", variable=self.inf, command=self.inf_toggle).pack(side="left", padx=4)
        ttk.Label(top, text="   Stop key: F3", foreground="#666").pack(side="right")

        self.status = tk.StringVar(value="Idle")
        ttk.Label(root, textvariable=self.status, padding=(8, 0), font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.last = tk.StringVar()
        ttk.Label(root, textvariable=self.last, padding=(8, 0), foreground="#555").pack(anchor="w")
        self.stats = tk.StringVar()
        ttk.Label(root, textvariable=self.stats, padding=(8, 0)).pack(anchor="w")

        ttk.Label(root, text="Flagged servers (candidates only; the detector has false alarms, so check the picture)",
                  padding=(8, 8, 8, 2)).pack(anchor="w")
        cols = ("scanned", "age", "frames", "strength", "server")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", height=10, selectmode="browse")
        for c, t, w in (("scanned", "Scanned", 110), ("age", "Server age (at least)", 130), ("frames", "Frames", 90),
                        ("strength", "Strength", 80), ("server", "Server id", 420)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.bind("<Double-1>", lambda e: self.join())
        self.tree.tag_configure("fresh", background="#fff3b0")

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        ttk.Button(bar, text="Join selected", command=self.join).pack(side="left")
        ttk.Button(bar, text="View picture", command=self.picture).pack(side="left", padx=4)
        ttk.Button(bar, text="Copy join link", command=self.copy).pack(side="left")
        ttk.Button(bar, text="Mark false alarm", command=self.dismiss).pack(side="left", padx=4)
        ttk.Button(bar, text="It's a spook!", command=self.confirm).pack(side="left")
        ttk.Button(bar, text="Open runs folder", command=lambda: os.startfile(RUNS)).pack(side="right")
        self.seen_flagged = set(self.rows)
        self.first_load = True
        self.tick()

    def inf_toggle(self):
        self.maxbox.config(state="disabled" if self.inf.get() else "normal")

    # ---- control
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def toggle(self):
        if self.running():
            open(STOP_FILE, "w").close()  # the hunter's watcher releases keys and exits
            self.status.set("Stopping...")
            return
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)
        os.makedirs(RUNS, exist_ok=True)
        cmd = [PY, "-u", os.path.join(HERE, "lt2_hunt.py")]
        if not self.inf.get():
            cmd += ["--max", self.maxn.get()]
        if float(self.age.get() or 0) > 0:
            cmd += ["--min-age-hours", self.age.get()]
        self.out = open(STDOUT, "w", encoding="utf-8")
        self.proc = subprocess.Popen(cmd, cwd=HERE, stdout=self.out, stderr=subprocess.STDOUT,
                                     creationflags=0x08000000)  # no console window
        self.started = time.time()

    # ---- flagged actions
    def sel(self):
        s = self.tree.selection()
        return self.rows.get(s[0]) if s else None

    def join(self):
        r = self.sel()
        if r:
            os.startfile(join_link(r["sid"]))

    def copy(self):
        r = self.sel()
        if r:
            self.root.clipboard_clear()
            self.root.clipboard_append(join_link(r["sid"]))

    def picture(self):
        r = self.sel()
        if r:
            try:
                os.startfile(make_marked(r["tag"], [int(i) for i in r["frames"].split(",")]))
            except Exception as e:
                messagebox.showinfo("No picture", f"Could not build the marked picture: {e}")

    def dismiss(self):
        r = self.sel()
        if r:
            try:
                save_samples(r["tag"], [int(i) for i in r["frames"].split(",")], "false_alarm")
            except Exception as e:
                self.last.set(f"could not save samples: {e}")
            with open(REVIEWED, "a") as f:
                f.write(r["tag"] + "\n")

    def confirm(self):
        r = self.sel()
        if r:
            save_samples(r["tag"], [int(i) for i in r["frames"].split(",")], "spook")
            messagebox.showinfo("Saved", "Filed as a confirmed spook in dataset/spook. It stays in the list; "
                                "join it now before the server changes.")

    # ---- refresh
    def tick(self):
        try:
            self.refresh()
        except Exception as e:  # keep the panel alive whatever happens
            self.last.set(f"refresh error: {e}")
        self.root.after(2000, self.tick)

    def refresh(self):
        if self.proc and self.proc.poll() is not None:
            if os.path.exists(STOP_FILE):
                os.remove(STOP_FILE)
            self.proc = None
        run = self.running()
        self.btn.config(text="Stop hunt" if run else "Start hunt")
        try:
            lines = open(STDOUT, encoding="utf-8", errors="replace").read().strip().splitlines()
        except OSError:
            lines = []
        self.last.set(lines[-1] if lines else "")
        if run:
            self.status.set("Hunting" + (" (stopping...)" if os.path.exists(STOP_FILE) else ""))
        else:
            tail = lines[-1] if lines else ""
            self.status.set("Stopped" if lines else "Idle - press Start")
            if "stopped by" in tail or "finished" in tail or "no unused" in tail:
                self.status.set(tail)

        log = read_log()
        nights = sum(1 for f in os.listdir(RUNS) if f.endswith("_NIGHT.jpg")) if os.path.isdir(RUNS) else 0
        self.stats.set(f"Day servers scanned: {len(log)}   Night skipped: {nights}   "
                       f"Flagged: {sum(1 for v in log.values() if v[2])}")
        done = reviewed()
        want = {}
        for tag, (sid, scores, flagged) in log.items():
            if not flagged or tag in done:
                continue
            folder = os.path.join(RUNS, tag)
            meta = {}
            try:
                meta = json.load(open(os.path.join(folder, "meta.json")))
            except (OSError, ValueError):
                pass
            ts = meta.get("ts") or (os.path.getmtime(folder) if os.path.isdir(folder) else time.time())
            age = meta.get("age_hours_min")
            want[tag] = dict(tag=tag, sid=sid, ts=ts, frames=",".join(str(i) for i in flagged),
                             strength=max(scores), age=("%.1f h+" % age) if age is not None else "unknown")
        for iid in list(self.tree.get_children()):
            if iid not in want:
                self.tree.delete(iid)
                self.rows.pop(iid, None)
        for tag, r in sorted(want.items(), key=lambda kv: -kv[1]["ts"]):
            vals = (ago(r["ts"]), r["age"], r["frames"], r["strength"], r["sid"])
            if tag in self.rows:
                self.tree.item(tag, values=vals)
            else:
                self.tree.insert("", 0, iid=tag, values=vals, tags=("fresh",) if not self.first_load else ())
                if not self.first_load:
                    self.root.bell()
                    self.root.deiconify()
                    self.root.attributes("-topmost", True)
                    self.root.attributes("-topmost", False)
            self.rows[tag] = r
        # keep newest on top
        for i, (tag, _) in enumerate(sorted(want.items(), key=lambda kv: -kv[1]["ts"])):
            self.tree.move(tag, "", i)
        self.first_load = False


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
