# LT2 Spook Hunter

**Let your PC server-hop Lumber Tycoon 2 for Spook trees while you do something else.**

Spook trees only grow in October, there are a couple per server at most, and finding one
normally means hours of joining servers, loading your base, and squinting at the horizon.
LT2 Spook Hunter does that loop for you on Windows: it joins a server, skips it if it's
night, loads your lookout base, photographs the whole map around it, looks for black bare
trees, and moves on. When it sees something it pops its window to the front, beeps, and
gives you a one-click **Join** button for that exact server.

**Video walkthrough:** https://youtu.be/Km66AARWvcU

![Control panel](docs/panel.png)

> **Use at your own risk.** This is an input-automation tool (it moves the mouse and presses
> keys for you, like a macro). It does not inject into or modify Roblox, but automating
> gameplay may be against Roblox's Terms of Use. Not affiliated with Roblox or Defaultio.

## What it does, per server

1. **Picks a server.** Random public servers, or (with the optional age tracker) only
   servers that have been up long enough to have grown a Spook tree.
2. **Skips night.** Night and fog hide black trees, so night servers are skipped.
3. **Loads save slot 2** — your lookout base.
4. **Ground-level survey.** On the plot-select screen the camera orbits each plot; the
   hunter grabs frames of the first few plots, so it sees the ground near the plots.
5. **Tower sweep.** In first person on top of your base it levels the camera on the
   horizon and turns a full circle, then does a second circle tilted toward the ground.
6. **Detects** near-black, colourless shapes (Spook bark is black and the tree is bare) and
   saves every frame plus a contact sheet, flagged or not.
7. **Alerts you** in the control panel with a Join button, the server's age, and a picture
   with red boxes around what it found.

About 2 minutes per server, roughly 30 images each.

![One server's sweep, as a contact sheet](docs/sweep_sheet_example.jpg)

## Get it (2 minutes, no Python needed)

1. Go to **[Releases](https://github.com/tiiow-fedora/lt2-spook-hunter/releases/latest)** and
   download **`LT2SpookHunter.exe`**.
2. Make a new folder (for example `Documents\LT2 Spook Hunter`) and put the exe in it.
   Its pictures and settings will be saved in that folder.
3. Double-click it.

**"Windows protected your PC"?** The exe isn't code-signed (that costs money), so Windows
warns about it. Click **More info → Run anyway**. Some antivirus tools also distrust any
program that moves the mouse and watches for a hotkey; the full source is in this repo if
you'd rather run it from Python (below).

## What you need

- **Windows 10 or 11** and the **Roblox app**.
- **Roblox fullscreen on your main monitor** (press **F11** in Roblox). A normal widescreen
  monitor (16:9, like 1920×1080).
- **A lookout base in save slot 2.** The hunter loads slot 2 in every server, and after
  loading you should end up **high up with a clear view all around**. The author's base is
  a tall tower that you spawn on top of. If you load your base and you're standing on the
  ground, the hunter will notice and skip that server, so build up.

## First run: Test my setup

1. Open Roblox and join any Lumber Tycoon 2 server. Close any menus.
2. In the panel press **Test my setup**. It checks your monitor, that Roblox is fullscreen on
   the main monitor, that LT2 is loaded, and that there's disk space, and tells you in plain
   English what to fix.
3. If everything is OK it offers a **full test**: it loads slot 2, goes first person on your
   base and does one sweep, then shows you the pictures. If they show the land around your
   base, you're ready.

## Hunt

1. Choose **Max servers** or tick **Infinite**, then press **Start hunt**.
2. Don't touch the mouse while it runs: it needs the Roblox window.
3. **Press F3 at any time to stop.** It lets go of every key and button first.

When a server is flagged:

- **View picture**: the flagged frames with red boxes on the suspects.
- **Join selected**: opens that exact server in Roblox.
- **Mark false alarm**: hides it and saves the crops to `data/dataset/false_alarm`.
- **It's a spook!**: saves it to `data/dataset/spook` (please share these: real examples
  are what improve the detector).

Every frame is kept in `data/runs/<time>_<server>/`; `sheet.jpg` in each folder shows a
whole server at a glance.

## Finding old servers (optional, recommended)

A new server can't have a Spook tree: the first sapling only appears after roughly
**6 hours of uptime**, and it takes about 3 more hours to grow. Roblox doesn't tell you a
server's age, so the included tracker checks the public server list every 10 minutes and
remembers when it first saw each server.

- **Easy way:** download **`Install.age.tracker.bat`** from the same Release, put it next to
  the exe, and double-click it once. Leave your PC on.
- After a few hours, type **6** in **"Only servers older than (h)"**. Ages are lower bounds:
  a server is *at least* that old.
- **Always-on Linux box / NAS instead:** copy the `tracker` folder there, run
  `sh install_cron.sh`, and add to `config.json`:
  `"tracker": {"ssh": ["ssh", "user@host"], "alive_path": "/path/to/tracker/alive.json"}`.

## Running from Python instead

1. Install **Python 3.10+** from python.org and tick **"Add python.exe to PATH"**.
2. On this page click the green **Code** button → **Download ZIP**, and extract it.
3. Double-click **`Install requirements.bat`** (once), then **`Start LT2 Spook Hunter.bat`**.

## Settings (optional)

Create `config.json` next to the exe (or the scripts); see `config.example.json`:

| key | meaning |
| --- | --- |
| `data_dir` | where pictures go (they add up: point it at a big drive) |
| `tracker` | where to read the age tracker's `alive.json` (only needed if it runs elsewhere) |
| `swamp_pass` | extra close-up pass aimed at the swamp; tuned for the author's tower, leave `false` |

Command-line options: `LT2SpookHunter.exe --hunt --help` or `python lt2_hunt.py --help`.

## How detection works

Daytime LT2 scenery is never pure black and colourless, but Spook bark is. The detector
downsizes each frame, masks the HUD, and looks for near-black neutral blobs (plus thin dark
branch-like features). Frames are also checked in quarters at double resolution so far-away
trees aren't lost. Expect some false alarms — dark pines on snow, shadows, players' builds —
and use **Mark false alarm** to keep your list clean.

![A false alarm: a player's dark roof, boxed in red](docs/false_alarm_example.jpg)

## Troubleshooting

- **It clicks in the wrong places / nothing happens**: Roblox must be fullscreen (F11) on the
  main monitor. Run **Test my setup**.
- **"You may only load once every 60 seconds"**: normal; the hunter waits it out.
- **"sweep was taken on the ground"**: your slot 2 base didn't put you up high. Build a tower.
- **Leveling fails / sweeps look at the sky**: your base needs a clear view of the horizon.
- **Server list errors (HTTP 429)**: Roblox rate-limits the list; with the tracker set up the
  hunter falls back to the tracker's list automatically.
- **Safety**: the hunter only ever loads. If LT2's "replace this save slot?" box ever appears,
  it presses Back and leaves the server.

## License

MIT
