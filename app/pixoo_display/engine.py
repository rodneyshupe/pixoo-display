"""Decides what is on the Pixoo and keeps it there. One tick a second; the Pixoo only hears about it when the picture changes."""
import datetime
import json
import threading
import time
from zoneinfo import ZoneInfo

from . import config, games as gm, render, sprites, weather

WEATHER_EVERY = 600      # seconds between weather reads
FRAME_MS = 1000          # frame time for a single picture
PLAY_MS = 2000           # frame time of the games loop. The Pixoo takes this literally only up to about 2 s (4000 gave
                         # 2 s, 8000 under 1 s, 15000 about 3 s), so a game is held for several identical 2 s frames.
MAX_LOOP = 40            # most frames in one upload (36 was tested on the device)


def game_text(g):
    """'NFL SEA 24 @ CHI 17' (away first) or, for soccer, 'MLS VAN 5 v SEA 1' (home first)."""
    first, second, sep = render.listing(g)
    return "%s %s %s %s %s %s" % (g["league_name"], first["abbr"], first["score"], sep, second["abbr"], second["score"])


def hex_frame(frame):
    return [["#%02x%02x%02x" % px for px in row] for row in frame]


class WeatherCache(threading.Thread):
    """Weather for every saved city, read from Open-Meteo in the background (every 10 minutes, and straight away for a new
    city), so the display never waits on the network. A failed read keeps the last good value."""

    def __init__(self, store, log=print):
        super().__init__(daemon=True, name="weather")
        self.store, self.log = store, log
        self.data = {}                  # (lat, lon) -> {"temp", "cond", "tz", "at"}
        self.wake = threading.Event()

    def get(self, city):
        return self.data.get((city["lat"], city["lon"]))

    def run(self):
        while True:
            for c in self.store.get()["cities"]:
                key = (c["lat"], c["lon"])
                have = self.data.get(key)
                if have and time.time() - have["at"] < WEATHER_EVERY:
                    continue
                try:
                    temp, cond, tz = weather.current(c["lat"], c["lon"])
                    self.data[key] = {"temp": temp, "cond": cond, "tz": tz, "at": time.time()}
                except Exception as e:
                    self.log("weather read for %s failed: %s" % (c["name"], e))
                    if have:
                        have["at"] = time.time() - WEATHER_EVERY + 60          # try again in a minute
                    else:
                        self.data[key] = {"temp": None, "cond": None, "tz": None, "at": time.time() - WEATHER_EVERY + 60}
            self.wake.wait(20)
            self.wake.clear()


class Engine(threading.Thread):
    def __init__(self, store, games, pixoo, log=print):
        super().__init__(daemon=True, name="engine")
        self.store, self.games, self.pixoo, self.log = store, games, pixoo, log
        self.weather = WeatherCache(store, log)
        self.canvas = render.blank_frame()            # the drawing buffer the draw API paints into
        self.draw_until = 0.0                         # a drawing is on the Pixoo until this time (inf = until cleared); 0 = none
        self.now_showing = {"mode": "", "label": "starting", "frame": None, "since": None}
        self.last_key = None
        self.was_off = False
        self.selected = []
        self.wake = threading.Event()

    # ---- inputs
    def clock_plan(self, s):
        """The clock: the weather and local time of each saved city. With several, each city gets a short frame with its code
        first, and the cities cycle (`city_seconds` each); with one it is a single picture."""
        units, now = s["units"], config.now()
        cities = [c for c in s["cities"] if c.get("on", True)] or s["cities"][:1]      # the ones switched on
        shown = []
        for c in cities:
            w = self.weather.get(c) or {"temp": None, "cond": None, "tz": None}
            try:
                local = now.astimezone(ZoneInfo(w["tz"])) if w["tz"] else now
            except Exception:
                local = now
            shown.append({"city": c, "local": local, "data": render.build_frame(w["temp"], w["cond"], local, units),
                          # the city code only matters when there are several to tell apart
                          "label": ("%s " % c["code"] if len(cities) > 1 else "") + "%s %s" % (render.temp_text(w["temp"], units), local.strftime("%H:%M"))})
        if len(shown) == 1:
            return {"frames": [shown[0]["data"]], "ms": FRAME_MS, "label": shown[0]["label"], "interval": 0,
                    "playlist": [{"label": shown[0]["label"], "frame": shown[0]["data"]}]}
        per = max(2, round(s["city_seconds"] * 1000 / PLAY_MS))               # frames per city, the code frame included
        per = max(2, min(per, MAX_LOOP // len(shown)))
        frames = []
        for x in shown:
            frames += [render.build_city_frame(x["city"]["code"], x["local"])] + [x["data"]] * (per - 1)
        return {"frames": frames, "ms": PLAY_MS, "label": " · ".join(x["label"] for x in shown), "interval": per * PLAY_MS // 1000,
                "playlist": [{"label": x["label"], "frame": x["data"]} for x in shown]}

    def update_selection(self, settings, now):
        today, _ = self.games.today()
        selected, to_note = gm.choose(today, settings, now)
        selected = [gm.colourise(g, settings["colours"]) for g in selected]
        for gid, when in to_note.items():
            self.store.note_final(gid, when)
        self.selected = selected
        return selected

    # ---- the drawing API (what pixoo-rest did for Home Assistant): paint into the buffer, then show it
    def draw(self, op, p, push=True, seconds=30):
        """op: fill | pixel | rectangle | text | clear. Colours are r, g, b (0-255). With push the buffer is shown on the Pixoo for
        `seconds` (0 = until cleared) and the normal programme then resumes; without push it is only painted, for a later push."""
        def colour(default=(255, 255, 255)):
            return tuple(max(0, min(255, int(p.get(k, d)))) for k, d in zip("rgb", default))

        i = lambda k, d=0: int(p.get(k, d))
        if op == "clear":
            self.canvas = render.blank_frame()
            self.draw_until = 0.0
            self.wake.set()
            return
        if op == "fill":
            self.canvas = [[colour((0, 0, 0))] * render.SIZE for _ in range(render.SIZE)]
        elif op == "pixel":
            x, y = i("x"), i("y")
            if 0 <= x < render.SIZE and 0 <= y < render.SIZE:
                self.canvas[y][x] = colour()
        elif op == "rectangle":
            render.draw_rect(self.canvas, i("x1"), i("y1"), i("x2"), i("y2"), colour(), bool(p.get("fill", True)))
        elif op == "text":
            render.draw_text(self.canvas, str(p.get("text", "")), i("x", 1), i("y", 1), colour())
        else:
            raise ValueError("unknown drawing command %r" % op)
        if push:
            self.draw_until = time.time() + seconds if seconds > 0 else float("inf")
            self.wake.set()

    def drawing(self):
        """True while a drawing is being shown instead of the normal programme."""
        if self.draw_until and time.time() >= self.draw_until:
            self.draw_until = 0.0
        return bool(self.draw_until)

    # ---- the timer (the Pixoo's own tool does the displaying and the beeping)
    FINISHED_HOLD = 12                                       # seconds the service stays out of the way after a timer ends

    def timer_action(self, action, seconds=0):
        """start (seconds) | pause | resume | cancel. Returns the saved timer. Raises RuntimeError if the Pixoo does not answer."""
        t, now = self.store.get()["timer"], time.time()
        if action == "start":
            seconds = int(seconds)
            if not 1 <= seconds <= 99 * 60 + 59:
                raise ValueError("a timer is 1 second to 99 minutes 59 seconds")
            if not self.pixoo.timer(seconds):
                raise RuntimeError("the Pixoo did not answer")
            self.store.set_timer("running", now + seconds, seconds, seconds)
        elif action == "pause" and t["state"] == "running":
            left = max(1, int(t["end"] - now))
            self.pixoo.timer(0, run=False)
            self.store.set_timer("paused", 0, t["total"], left)
        elif action == "resume" and t["state"] == "paused":
            if not self.pixoo.timer(t["remaining"]):
                raise RuntimeError("the Pixoo did not answer")
            self.store.set_timer("running", now + t["remaining"], t["total"], t["remaining"])
        elif action == "cancel":
            if t["state"] != "idle":
                self.pixoo.timer(0, run=False)
            self.store.set_timer("idle")
        else:
            raise ValueError("cannot %s a timer that is %s" % (action, t["state"]))
        self.wake.set()
        return self.store.get()["timer"]

    def timer_plan(self):
        """While a timer runs (and a few seconds after it ends) the Pixoo shows its own: send nothing. None when there is no timer."""
        t, now = self.store.get()["timer"], time.time()
        if t["state"] == "paused":                           # stopped on the Pixoo's screen: leave it there until resumed or cancelled
            return {"mode": "timer", "label": "Timer paused", "frames": [render.build_timer_preview(t["remaining"])], "ms": FRAME_MS,
                    "playlist": [], "interval": 0, "hold": True}
        if t["state"] == "running":
            if now < t["end"]:
                left = t["end"] - now
                return {"mode": "timer", "label": "Timer running", "frames": [render.build_timer_preview(left)],
                        "ms": FRAME_MS, "playlist": [], "interval": 0, "hold": True}
            if now < t["end"] + self.FINISHED_HOLD:
                return {"mode": "timer", "label": "Timer finished", "frames": [render.build_timer_preview(0)], "ms": FRAME_MS,
                        "playlist": [], "interval": 0, "hold": True}
            self.store.set_timer("idle")                     # done: the normal programme is sent again from here
            self.pixoo.digest = None
        return None

    # ---- countdowns
    def countdown_plan(self, s, now):
        """Each countdown that is on: a short name frame, then the number of days / hours / minutes left (twice the size).
        A yearly one counts down to its next occurrence; a one-off stays for the day it happens, then drops out."""
        items = []
        for ev in s["countdowns"]:
            if not ev["on"]:
                continue
            at = datetime.datetime.strptime(ev["at"], "%Y-%m-%dT%H:%M")
            if ev["yearly"]:
                def in_year(y):
                    try:
                        return at.replace(year=y, tzinfo=config.TZ)
                    except ValueError:                                   # 29 February in a year without one
                        return at.replace(year=y, day=28, tzinfo=config.TZ)

                when = in_year(now.year)
                if when < now - datetime.timedelta(days=1):              # this year's has gone: the next one
                    when = in_year(now.year + 1)
            else:
                when = at.replace(tzinfo=config.TZ)
            left = (when - now).total_seconds()
            if left < -86400:                                            # a one-off that is more than a day past
                continue
            rgb = tuple(int(ev["colour"][i:i + 2], 16) for i in (1, 3, 5))
            number, unit = render.countdown_units(left) if left > 0 else ("NOW", "")
            items.append({"ev": ev, "rgb": rgb, "label_frame": render.build_countdown_label(ev["code"], rgb),
                          "number_frame": render.build_countdown_number(number, unit, rgb),
                          "text": "%s: %s %s" % (ev["name"], number, unit.lower()) if unit else "%s: now" % ev["name"]})
        return items

    # ---- what to show
    def plan(self):
        """What the Pixoo should be showing now: mode, label, frames, ms per frame, and the per-game list for the web preview."""
        s, now = self.store.get(), config.now()
        mode = s["mode"]
        tp = self.timer_plan() if not self.drawing() else None
        if tp:
            return tp
        if self.drawing():
            return {"mode": "draw", "label": "Custom drawing" + (" (until cleared)" if self.draw_until == float("inf") else ""), "frames": [self.canvas], "ms": FRAME_MS, "playlist": [], "interval": 0}
        if mode == "visualizer":
            favs = [x for x in s["vis_favourites"] if x < s["vis_styles"]]
            style = favs[int(time.time() // s["vis_cycle_seconds"]) % len(favs)] if s["vis_cycle"] and favs else s["vis_style"]
            name = s["vis_names"].get(str(style))
            return {"mode": "visualizer", "label": "Music visualizer, style %d%s" % (style, " (%s)" % name if name else ""),
                    "frames": [render.build_visualizer_preview(style)], "ms": FRAME_MS, "playlist": [], "interval": 0, "visualizer": style}
        if mode == "countdown":
            items = self.countdown_plan(s, now)
            if items:
                per = max(2, round(s["countdown_seconds"] * 1000 / PLAY_MS))
                per = max(2, min(per, MAX_LOOP // len(items)))
                frames = []
                for it in items:
                    frames += [it["label_frame"]] + [it["number_frame"]] * (per - 1)
                return {"mode": "countdown", "label": " · ".join(it["text"] for it in items), "frames": frames, "ms": PLAY_MS,
                        "playlist": [{"label": it["text"], "frame": it["number_frame"]} for it in items],
                        "interval": per * PLAY_MS // 1000}
        if mode == "gifs":
            names = [n for n, on in self.store.animations(sprites.names()) if on]    # the saved order, minus the ones switched off
            if names:
                name = names[int(time.time() // 60) // max(1, s["gif_minutes"]) % len(names)]
                try:
                    frames, ms = sprites.build(name)
                    return {"mode": "gifs", "label": name, "frames": frames, "ms": ms, "playlist": [], "interval": 0}
                except Exception as e:
                    self.log("animation %s could not be read: %s" % (name, e))
        elif mode == "scores":
            selected = self.update_selection(s, now)
            if selected:
                pics = [render.score_pictures(g, now) for g in selected]          # one picture per game, two for a 3-digit score
                reps = max(1, round(s["dwell"] * 1000 / PLAY_MS))                 # 2 s frames a game is held for

                def holds(n, r):
                    """Frames each picture of a game is held: all of them for a single picture; for a 3-digit score the names
                    come first for one frame (2 s) and the scores get the rest."""
                    return [r] if n == 1 else [1, max(1, r - 1)]

                while sum(sum(holds(len(p), reps)) for p in pics) > MAX_LOOP and reps > 1:
                    reps -= 1
                playlist, frames = [], []
                for g, ps in zip(selected, pics):
                    for i, (pic, hold) in enumerate(zip(ps, holds(len(ps), reps))):
                        part = "" if len(ps) == 1 else (" · names" if i == 0 else " · scores")
                        playlist.append({"label": game_text(g) + part, "frame": pic, "secs": hold * PLAY_MS // 1000})
                        frames += [pic] * hold
                if len(playlist) == 1:                                           # one picture: just show it, nothing to loop
                    frames, ms = [playlist[0]["frame"]], FRAME_MS
                else:
                    ms = PLAY_MS
                return {"mode": "scores", "label": " · ".join(game_text(g) for g in selected), "frames": frames, "ms": ms,
                        "playlist": playlist, "interval": 0}
        c = self.clock_plan(s)
        return {"mode": "clock", "label": ("No selected games today · " if mode == "scores" else "") + c["label"], "frames": c["frames"],
                "ms": c["ms"], "playlist": c["playlist"], "interval": c["interval"]}

    def tick(self):
        s = self.store.get()
        if s["brightness"] is None:                          # first run: keep whatever the Pixoo is set to
            b = self.pixoo.read_brightness()
            if b:
                self.store.set_brightness_if_unset(b)
                s = self.store.get()
        self.pixoo.apply_power(s["screen_on"], s["brightness"])
        if not s["screen_on"]:                               # off: nothing is sent; the picture is sent again when it comes on
            self.was_off = True
            self.now_showing = {"mode": "off", "label": "Display off", "frame": hex_frame(render.blank_frame()), "since": time.time(),
                                "frames": 0, "ms": 0, "interval": 0, "playlist": []}
            return
        if self.was_off:
            self.pixoo.digest = None                         # send the picture again
            self.last_key = None                             # and refresh the "now showing" record
            self.was_off = False
        p = self.plan()
        if p.get("hold"):                                    # the Pixoo's timer is on screen: leave it alone
            pass
        elif p.get("visualizer") is not None:                  # the Pixoo draws this one itself: only the style is sent
            self.pixoo.ensure_visualizer(p["visualizer"])
        else:
            self.pixoo.show(p["frames"], p["ms"])
        key = (p["mode"], p["label"], json.dumps(p["frames"]))
        if key != self.last_key:
            self.last_key = key
            self.now_showing = {"mode": p["mode"], "label": p["label"] or "Clock", "frame": hex_frame(p["frames"][0]),
                                "since": time.time(), "frames": len(p["frames"]), "ms": p["ms"], "interval": p.get("interval", 0),
                                "playlist": [{"label": g["label"], "frame": hex_frame(g["frame"])} for g in p["playlist"]]}

    def run(self):
        self.weather.start()
        while True:
            try:
                self.tick()
            except Exception as e:                      # a bug must not stop the display
                self.log("engine error: %s: %s" % (type(e).__name__, e))
            self.wake.wait(1)
            self.wake.clear()
