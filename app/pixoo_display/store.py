"""The settings the web app and Home Assistant change while the service runs, kept in DATA_DIR/settings.json."""
import copy
import datetime
import json
import os
import threading

from . import config, render

MODES = ("clock", "scores", "gifs", "countdown", "visualizer")

DEFAULTS = {
    "mode": "scores",          # clock | scores | gifs | countdown | visualizer
    "screen_on": True,         # the display itself on/off (the Pixoo's own screen switch)
    "brightness": None,        # 1-100; None until set: then the Pixoo's own setting is read and kept
    "dwell": 12,               # about how many seconds a game in progress is shown (rounded to the Pixoo's 2 s frames)
    "dwell_pre": 8,            # ... a game that has not started yet
    "dwell_post": 6,           # ... a finished game
    "gif_minutes": 2,          # minutes each animation plays in gifs mode
    "final_hours": 3,          # a finished game of a followed team stays in the rotation this long
    # Followed teams: their game today is shown without picking it. key = league:ESPN abbreviation (CFL: see games.py).
    "teams": [
        {"key": "cfl:BC", "name": "BC Lions", "on": True},
        {"key": "nfl:SEA", "name": "Seahawks", "on": True},
        {"key": "mls:VAN", "name": "Whitecaps", "on": True},
        {"key": "nhl:VAN", "name": "Canucks", "on": True},
        {"key": "mlb:SEA", "name": "Mariners", "on": True},
        {"key": "mlb:TOR", "name": "Blue Jays", "on": True},
    ],
    # Leagues whose games are fetched and listed (the catalogue is games.LEAGUES). NWSL is off until you want it.
    "leagues": ["nfl", "cfl", "nhl", "nba", "mlb", "mls", "epl", "ucl"],
    # Team colours that replace the feed's ('#rrggbb' by team key); set in the web app by clicking a team.
    "colours": {"mls:VAN": "#5abeff", "mlb:TOR": "#5abeff", "mls:POR": "#1faa4a"},
    # The clock cycles through these cities (weather from Open-Meteo, and each city's own local time). `code` is the 3-letter
    # label shown before a city when there are several. Add, remove and reorder them in the web app (Clock tab).
    "cities": [{"name": "Vancouver, British Columbia, Canada", "lat": 49.2827, "lon": -123.1207, "code": "VAN", "on": True}],
    "units": "C",              # C | F
    "city_seconds": 8,         # about how long each city is shown when there are several (2 s steps)
    # Countdowns to dates: [{name, code (up to 4 letters), at "YYYY-MM-DDTHH:MM" local, colour "#rrggbb", on, yearly}].
    # The countdown mode cycles through the ones that are on, a short name frame and then the big number of days / hours / minutes left.
    "countdowns": [],
    "countdown_seconds": 8,    # about how long each countdown is shown (2 s steps)
    # The Pixoo's own music visualizer (its microphone, its drawing): which style is on, which ones are favourites to cycle through.
    "vis_style": 0,
    "vis_styles": 10,          # how many styles the buttons offer (the device does not say how many it has)
    "vis_favourites": [],
    "vis_cycle": False,        # step through the favourites
    "vis_cycle_seconds": 30,
    "vis_names": {},           # style number (as text) -> your name for it
    # The timer runs on the Pixoo's own timer tool (it counts down on screen and beeps); this remembers it so the web app and Home
    # Assistant know what is running. state: idle | running | paused; end = when it finishes (epoch s); remaining = left when paused.
    "timer": {"state": "idle", "end": 0, "total": 0, "remaining": 0},
    "timer_minutes": 5,        # the length Home Assistant's "Start timer" button uses
    # Animations: the play order and the ones switched off. A GIF that is not in `order` yet (a new upload) is added at the end.
    "animations": {"order": [], "off": []},
    "pins": {},                # picked games: game id -> {"day": the game's day (YYYY-MM-DD), "label": text}; dropped after that day
    "finals": {},              # game id -> when it was first seen finished (ISO), to time a final out of the rotation
}
LIMITS = {"dwell": (4, 60), "dwell_pre": (2, 60), "dwell_post": (2, 60), "gif_minutes": (1, 60), "final_hours": (0, 12), "city_seconds": (4, 60), "countdown_seconds": (4, 60),
          "vis_style": (0, 63), "vis_styles": (1, 32), "vis_cycle_seconds": (5, 600), "timer_minutes": (1, 99)}
MAX_COUNTDOWNS = 12
MAX_CITIES = 8


class Store:
    def __init__(self, path=None):
        self.path = path or os.path.join(config.DATA_DIR, "settings.json")
        self.lock = threading.RLock()
        self.listeners = []          # called with no arguments after every change
        self.data = copy.deepcopy(DEFAULTS)
        try:
            with open(self.path) as f:
                saved = json.load(f)
            for k in DEFAULTS:
                if k in saved:
                    self.data[k] = saved[k]
            if "cities" not in saved and isinstance(saved.get("location"), dict):          # the single location of earlier versions
                loc = saved["location"]
                self.data["cities"] = [{"name": loc["name"], "lat": loc["lat"], "lon": loc["lon"], "code": render.city_code(loc["name"]), "on": True}]
        except (OSError, ValueError):
            pass
        self.prune()

    def get(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=1)
        os.replace(tmp, self.path)
        for fn in list(self.listeners):
            try:
                fn()
            except Exception:
                pass

    def prune(self):
        """Forget picks from earlier days and finals of games that are long gone."""
        today = config.now().date().isoformat()
        with self.lock:
            pins = {}
            for k, v in self.data["pins"].items():
                v = v if isinstance(v, dict) else {"day": v, "label": ""}        # older settings stored just the day
                if v["day"] >= today:
                    pins[k] = v
            self.data["pins"] = pins
            cutoff = (config.now() - datetime.timedelta(days=2)).isoformat()
            self.data["finals"] = {k: v for k, v in self.data["finals"].items() if v >= cutoff}

    def update(self, **kw):
        """Set mode / dwell / gif_minutes / final_hours; values are validated and clamped. Returns the settings."""
        with self.lock:
            for k, v in kw.items():
                if k == "mode":
                    if v not in MODES:
                        raise ValueError("mode must be one of %s" % ", ".join(MODES))
                    self.data["mode"] = v
                elif k == "vis_cycle":
                    self.data["vis_cycle"] = bool(v)
                elif k == "screen_on":
                    self.data["screen_on"] = bool(v)
                elif k == "brightness":
                    self.data["brightness"] = max(1, min(100, int(v)))
                elif k == "units":
                    if v not in ("C", "F"):
                        raise ValueError("units must be C or F")
                    self.data["units"] = v
                elif k in LIMITS:
                    lo, hi = LIMITS[k]
                    self.data[k] = max(lo, min(hi, int(v)))
                else:
                    raise ValueError("unknown setting %r" % k)
            self._save()
            return copy.deepcopy(self.data)

    def pin(self, game_id, on, day=None, label="", after_start=None):
        """Pick (or drop) a game. after_start: only show it once it has started (None keeps the current choice)."""
        with self.lock:
            if on:
                old = self.data["pins"].get(game_id, {})
                self.data["pins"][game_id] = {"day": day or old.get("day") or config.now().date().isoformat(),
                                              "label": label or old.get("label", ""),
                                              "after_start": bool(old.get("after_start", False) if after_start is None else after_start)}
            else:
                self.data["pins"].pop(game_id, None)
            self._save()

    def set_team(self, key, name=None, on=True):
        """Add a followed team, or switch one on or off."""
        with self.lock:
            for t in self.data["teams"]:
                if t["key"] == key:
                    t["on"] = bool(on)
                    if name:
                        t["name"] = name
                    break
            else:
                self.data["teams"].append({"key": key, "name": name or key.split(":")[-1], "on": bool(on)})
            self._save()

    def remove_team(self, key):
        with self.lock:
            self.data["teams"] = [t for t in self.data["teams"] if t["key"] != key]
            self._save()

    def set_brightness_if_unset(self, value):
        """Remember the brightness read from the device the first time (not a user change, so no listeners)."""
        with self.lock:
            if self.data["brightness"] is None:
                self.data["brightness"] = max(1, min(100, int(value)))
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path + ".tmp", "w") as f:
                    json.dump(self.data, f, indent=1)
                os.replace(self.path + ".tmp", self.path)

    def set_pin_label(self, game_id, label):
        """Fill in the name of a pick that was saved without one (not a user change, so no listeners)."""
        with self.lock:
            pin = self.data["pins"].get(game_id)
            if pin is not None and not pin.get("label") and label:
                pin["label"] = label
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path + ".tmp", "w") as f:
                    json.dump(self.data, f, indent=1)
                os.replace(self.path + ".tmp", self.path)

    def set_cities(self, cities):
        """Save the cities in the order given: [{name, lat, lon, code, on}]. At least one, and at least one of them on; at most MAX_CITIES."""
        out = []
        for c in cities:
            lat, lon = float(c["lat"]), float(c["lon"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("%s is not a place on Earth" % c.get("name", "that"))
            name = str(c.get("name") or "?")[:80]
            code = "".join(ch for ch in str(c.get("code") or "").upper() if ch.isalnum() and ch in render.G)[:3] or render.city_code(name)
            out.append({"name": name, "lat": round(lat, 4), "lon": round(lon, 4), "code": code, "on": bool(c.get("on", True))})
        if not out:
            raise ValueError("keep at least one city")
        if not any(c["on"] for c in out):
            raise ValueError("keep at least one city switched on")
        if len(out) > MAX_CITIES:
            raise ValueError("at most %d cities" % MAX_CITIES)
        with self.lock:
            self.data["cities"] = out
            self._save()

    def set_timer(self, state, end=0, total=0, remaining=0):
        with self.lock:
            self.data["timer"] = {"state": state, "end": end, "total": total, "remaining": remaining}
            self._save()

    def set_countdowns(self, events):
        """Save the countdowns in the order given. Each needs a name and a date and time."""
        out = []
        for e in events:
            name = str(e.get("name") or "").strip()[:40]
            if not name:
                raise ValueError("a countdown needs a name")
            try:
                at = datetime.datetime.fromisoformat(str(e["at"])).strftime("%Y-%m-%dT%H:%M")
            except (KeyError, ValueError):
                raise ValueError("%s needs a date and time" % name)
            code = "".join(c for c in str(e.get("code") or "").upper() if c.isalnum() and c in render.G)[:4] or \
                   "".join(c for c in name.upper() if c.isalnum() and c in render.G)[:4]
            colour = str(e.get("colour") or "#ffc83d").lower()
            if len(colour) != 7 or colour[0] != "#":
                raise ValueError("colour must look like #rrggbb")
            int(colour[1:], 16)
            out.append({"name": name, "code": code, "at": at, "colour": colour, "on": bool(e.get("on", True)), "yearly": bool(e.get("yearly", False))})
        if len(out) > MAX_COUNTDOWNS:
            raise ValueError("at most %d countdowns" % MAX_COUNTDOWNS)
        with self.lock:
            self.data["countdowns"] = out
            self._save()

    def set_vis_favourites(self, styles):
        with self.lock:
            self.data["vis_favourites"] = sorted({max(0, min(63, int(x))) for x in styles})
            self._save()

    def set_vis_name(self, style, name):
        with self.lock:
            names = self.data["vis_names"]
            if str(name or "").strip():
                names[str(int(style))] = str(name).strip()[:30]
            else:
                names.pop(str(int(style)), None)
            self._save()

    def set_animations(self, order, off):
        """Save the play order and which animations are switched off (names; unknown ones are kept until the GIF is gone)."""
        with self.lock:
            self.data["animations"] = {"order": [str(n) for n in order], "off": [str(n) for n in off]}
            self._save()

    def animations(self, existing):
        """[(name, on)] for the GIFs that exist, in the saved order; new ones at the end, switched on."""
        with self.lock:
            a = self.data["animations"]
            order = [n for n in a["order"] if n in existing] + [n for n in existing if n not in a["order"]]
            return [(n, n not in a["off"]) for n in order]

    def set_league(self, key, on):
        with self.lock:
            leagues = [k for k in self.data["leagues"] if k != key]
            if on:
                leagues.append(key)
            self.data["leagues"] = leagues
            self._save()

    def set_colour(self, key, colour):
        """Set a team's colour ('#rrggbb'), or None to go back to the feed's."""
        with self.lock:
            if colour:
                if len(colour) != 7 or colour[0] != "#":
                    raise ValueError("colour must look like #rrggbb")
                int(colour[1:], 16)
                self.data["colours"][key] = colour.lower()
            else:
                self.data["colours"].pop(key, None)
            self._save()

    def note_final(self, game_id, when_iso):
        """Remember when a game was first seen finished (not a user change, so no listeners)."""
        with self.lock:
            if game_id not in self.data["finals"]:
                self.data["finals"][game_id] = when_iso
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path + ".tmp", "w") as f:
                    json.dump(self.data, f, indent=1)
                os.replace(self.path + ".tmp", self.path)
