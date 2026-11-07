"""Today's games from ESPN's public scoreboards (and the CFL's own stats API, since ESPN has had no CFL data since 2022),
normalised to one shape, plus the choice of which of them to show.

A game is a dict:
  id, league (key), league_name, sport, periods, state (pre | in | post), period, clock, detail, start (aware datetime),
  skip (postponed / cancelled), away / home = {abbr (as drawn), key (league:abbr, for following a team), name, score, colour}
Everything is unofficial and may change; a league that fails keeps its last data and shows the error in the web app.
"""
import concurrent.futures
import datetime
import email.utils
import json
import threading
import time
import urllib.request

from . import config
from .render import team_colour

ESPN = "https://site.api.espn.com/apis/site/v2/sports/%s/scoreboard?dates=%s"
CFL_API = "https://api.stats.cfl.ca/fixtures/%d?view=full"

# key -> (name, ESPN path or None for the CFL feed, sport, periods). The catalogue; which ones are on is a setting (store.py),
# so a league is added or removed in the web app / Home Assistant without touching code. Order = the order in the web app.
LEAGUES = {
    "nfl": ("NFL", "football/nfl", "football", 4),
    "cfl": ("CFL", None, "football", 4),
    "ncaaf": ("College football", "football/college-football", "football", 4),
    "nhl": ("NHL", "hockey/nhl", "hockey", 3),
    "nba": ("NBA", "basketball/nba", "basketball", 4),
    "wnba": ("WNBA", "basketball/wnba", "basketball", 4),
    "ncaab": ("College basketball", "basketball/mens-college-basketball", "basketball", 2),
    "mlb": ("MLB", "baseball/mlb", "baseball", 9),
    "mls": ("MLS", "soccer/usa.1", "soccer", 2),
    "nwsl": ("NWSL", "soccer/usa.nwsl", "soccer", 2),
    "epl": ("Premier League", "soccer/eng.1", "soccer", 2),
    "ucl": ("Champions League", "soccer/uefa.champions", "soccer", 2),
    "uel": ("Europa League", "soccer/uefa.europa", "soccer", 2),
    "laliga": ("La Liga", "soccer/esp.1", "soccer", 2),
    "bundesliga": ("Bundesliga", "soccer/ger.1", "soccer", 2),
    "seriea": ("Serie A", "soccer/ita.1", "soccer", 2),
    "ligue1": ("Ligue 1", "soccer/fra.1", "soccer", 2),
}
SKIPPED = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED", "STATUS_FORFEIT"}

# CFL team id -> (key abbreviation, name, what the Pixoo shows, colour). Tune the last two here.
CFL_TEAMS = {
    1: ("BC", "BC Lions", "BC", (244, 121, 32)), 6: ("CGY", "Calgary Stampeders", "CG", (230, 30, 40)),
    7: ("EDM", "Edmonton Elks", "ED", (255, 190, 0)), 8: ("HAM", "Hamilton Tiger-Cats", "HA", (255, 150, 0)),
    11: ("MTL", "Montreal Alouettes", "MT", (230, 40, 90)), 13: ("OTT", "Ottawa REDBLACKS", "OT", (190, 20, 40)),
    17: ("SSK", "Saskatchewan Roughriders", "SK", (0, 170, 60)), 19: ("TOR", "Toronto Argonauts", "TO", (110, 170, 255)),
    20: ("WPG", "Winnipeg Blue Bombers", "WG", (60, 110, 255)),
}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pixoo-display"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _espn_games(league, day0):
    name, path, sport, periods = LEAGUES[league]
    seen = {}
    for day in (day0, day0 + datetime.timedelta(days=1)):    # ESPN dates run on US Eastern: a late local game is "tomorrow"
        for e in _get(ESPN % (path, day.strftime("%Y%m%d"))).get("events", []):
            seen[e["id"]] = e
    out = []
    for e in seen.values():
        comp, status = e["competitions"][0], e["status"]
        sides = {c["homeAway"]: c for c in comp["competitors"]}
        if len(sides) != 2:
            continue

        def side(c):
            t = c["team"]
            return {"abbr": (t.get("abbreviation") or "?").upper(), "key": "%s:%s" % (league, (t.get("abbreviation") or "?").upper()),
                    "name": t.get("displayName") or t.get("name") or "?", "score": _int(c.get("score")),
                    "colour": team_colour(t.get("color"), t.get("alternateColor"))}

        out.append({"id": "espn:%s:%s" % (league, e["id"]), "league": league, "league_name": name, "sport": sport,
                    "periods": periods, "state": status["type"]["state"], "period": _int(status.get("period")),
                    "clock": status.get("displayClock") or "", "detail": status["type"].get("shortDetail") or "",
                    "start": datetime.datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(config.TZ),
                    "skip": status["type"].get("name") in SKIPPED, "away": side(sides["away"]), "home": side(sides["home"])})
    return out


THESCORE_CFL = "https://api.thescore.com/cfl/events"


def _cfl_live(games):
    """The CFL stats API only publishes a score once a game is Finished, so overlay theScore's public feed (live score,
    quarter and clock) on the games it lists. Best effort: any failure leaves the stats-API data as it is."""
    try:
        events = _get(THESCORE_CFL)
    except Exception:
        return
    by_abbr = {t[0]: t for t in CFL_TEAMS.values()}
    for e in events:
        try:
            start = email.utils.parsedate_to_datetime(e["game_date"]).astimezone(config.TZ)
            ha, aa = e["home_team"]["abbreviation"], e["away_team"]["abbreviation"]
            status = e.get("status") or ""
            if ha not in by_abbr or aa not in by_abbr or status not in ("pre_game", "in_progress", "final"):
                continue
            g = next((x for x in games if x["home"]["key"] == "cfl:" + ha and x["away"]["key"] == "cfl:" + aa
                      and abs((x["start"] - start).total_seconds()) < 36 * 3600), None)
            if g is None or status == "pre_game":
                continue
            bs = e.get("box_score") or {}
            prog = bs.get("progress") or {}
            g["home"]["score"] = _int(((bs.get("score") or {}).get("home") or {}).get("score"))
            g["away"]["score"] = _int(((bs.get("score") or {}).get("away") or {}).get("score"))
            g["state"] = "in" if status == "in_progress" else "post"
            if g["state"] == "in":
                g["period"] = _int(prog.get("segment"))
                g["clock"] = prog.get("clock") or ""
                g["detail"] = prog.get("string") or "In progress"
            else:
                g["period"], g["clock"], g["detail"] = 0, "", "Final"
        except Exception:
            continue


def _cfl_games(day0):
    out = _cfl_stats(day0)
    _cfl_live(out)
    return out


def _cfl_stats(day0):
    d = _get(CFL_API % day0.year)
    name, _, sport, periods = LEAGUES["cfl"]
    now = config.now()
    out = []
    for bucket in ("season", "semiFinals", "finals"):
        for g in d.get(bucket, []):
            home, away = CFL_TEAMS.get(g.get("home_team_id")), CFL_TEAMS.get(g.get("away_team_id"))
            if not home or not away or not g.get("start_at"):
                continue                                      # a playoff slot whose teams are not decided yet
            start = datetime.datetime.fromisoformat(g["start_at"]).astimezone(config.TZ)
            if g.get("game_status") == "Finished":
                state = "post"
            elif start <= now and now - start < datetime.timedelta(hours=5):
                state = "in"
            elif start <= now:
                state = "post"
            else:
                state = "pre"

            def side(t, score):
                return {"abbr": t[2], "key": "cfl:" + t[0], "name": t[1], "score": _int(score), "colour": t[3]}

            out.append({"id": "cfl:%s" % g["ID"], "league": "cfl", "league_name": name, "sport": sport, "periods": periods,
                        "state": state, "period": _int(g.get("total_periods")) if state == "in" else 0,
                        "clock": (g.get("game_clock") or "") if state == "in" else "", "detail": g.get("game_status") or "",
                        "start": start, "skip": False, "away": side(away, g.get("away_team_score")),
                        "home": side(home, g.get("home_team_score"))})
    return out


class GamesService(threading.Thread):
    """Keeps the enabled leagues' games for today fresh (every 30 s while a game is on or about to start in the league, every
    5 minutes otherwise), and fetches any other day on request (cached for 5 minutes)."""

    def __init__(self, store):
        super().__init__(daemon=True, name="games")
        self.store = store
        self.lock = threading.Lock()
        self.games = {}                  # league -> today's games
        self.fetched = {}                # league -> time.time() of the last attempt
        self.errors = {}                 # league -> last error text
        self.other = {}                  # (league, day) -> (time.time(), games) for days other than today
        self.wake = threading.Event()

    def enabled(self):
        on = set(self.store.get()["leagues"])
        return [k for k in LEAGUES if k in on]

    def _due(self, league, now_ts):
        games = self.games.get(league)
        if games is None:
            return True
        busy = any(g["state"] == "in" or (g["state"] == "pre" and g["start"].timestamp() - now_ts < 1200) for g in games)
        ttl = 30 if busy else 300
        if league in self.errors:
            ttl = 60
        return now_ts - self.fetched.get(league, 0) >= ttl

    def refresh(self, league):
        today = config.now().date()
        try:
            games = _cfl_games(today) if league == "cfl" else _espn_games(league, today)
        except Exception as e:
            with self.lock:
                self.errors[league] = "%s: %s" % (type(e).__name__, e)
                self.fetched[league] = time.time()
            return
        with self.lock:
            self.games[league] = games
            self.fetched[league] = time.time()
            self.errors.pop(league, None)

    def run(self):
        while True:
            now_ts = time.time()
            for league in self.enabled():
                if self._due(league, now_ts):
                    self.refresh(league)
            self.wake.wait(5)
            self.wake.clear()

    def today(self):
        """Every game that starts today (local day) in the enabled leagues, with the leagues' last errors."""
        day = config.now().date()
        on = self.enabled()
        with self.lock:
            games = [g for league in on for g in self.games.get(league, []) if g["start"].date() == day and not g["skip"]]
            errors = {k: v for k, v in self.errors.items() if k in on}
        games.sort(key=lambda g: (list(LEAGUES).index(g["league"]), g["start"], g["id"]))
        return games, errors

    def find(self, game_id):
        """A game by id from anything fetched so far (today, or another day that was browsed), or None."""
        with self.lock:
            pools = list(self.games.values()) + [v[1] for v in self.other.values()]
        for games in pools:
            for g in games:
                if g["id"] == game_id:
                    return g
        return None

    def on_day(self, day):
        """Games on another local day (tomorrow, next week...), for picking ahead. Fetched in parallel, cached 5 minutes."""
        if day == config.now().date():
            return self.today()
        on = self.enabled()
        errors, out, todo = {}, [], []
        now_ts = time.time()
        for league in on:
            hit = self.other.get((league, day))
            if hit and now_ts - hit[0] < 300:
                out += hit[1]
            else:
                todo.append(league)

        def fetch(league):
            try:
                games = _cfl_games(day) if league == "cfl" else _espn_games(league, day)
                return league, [g for g in games if g["start"].date() == day and not g["skip"]], None
            except Exception as e:
                return league, [], "%s: %s" % (type(e).__name__, e)

        if todo:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                for league, games, err in pool.map(fetch, todo):
                    if err:
                        errors[league] = err
                    else:
                        self.other[(league, day)] = (now_ts, games)
                        out += games
            for k in [k for k, v in self.other.items() if now_ts - v[0] > 3600]:     # forget old days
                del self.other[k]
        out.sort(key=lambda g: (list(LEAGUES).index(g["league"]), g["start"], g["id"]))
        return out, errors


def colourise(g, overrides):
    """A copy of the game with the user's team colours ('#rrggbb' by team key) applied."""
    if not overrides or not (g["away"]["key"] in overrides or g["home"]["key"] in overrides):
        return g

    def side(s):
        h = overrides.get(s["key"])
        return dict(s, colour=tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))) if h else s

    return dict(g, away=side(g["away"]), home=side(g["home"]))


def held(g, settings):
    """A picked game (not of a followed team) that waits for its start before it joins the rotation."""
    followed = {t["key"] for t in settings["teams"] if t["on"]}
    pin = settings["pins"].get(g["id"])
    return bool(pin and pin.get("after_start") and g["state"] == "pre" and not (g["away"]["key"] in followed or g["home"]["key"] in followed))


def choose(games, settings, now, apply_hold=True):
    """The games to rotate through: today's games of followed teams plus the games picked in the web app.
    Live first, then the ones still to come (soonest first), then finals (a followed team's final drops out
    `final_hours` after it was first seen finished; a picked one stays until midnight).
    Returns (selected games, {id: first-seen-final ISO time to remember})."""
    followed = {t["key"] for t in settings["teams"] if t["on"]}
    pins = settings["pins"]
    finals = settings["finals"]
    keep, to_note = [], {}
    for g in games:
        pinned = g["id"] in pins
        followed_game = g["away"]["key"] in followed or g["home"]["key"] in followed
        if not (pinned or followed_game):
            continue
        if apply_hold and held(g, settings):
            continue                                          # picked "only once it has started"
        if g["state"] == "post":
            first = finals.get(g["id"])
            if first is None:                                 # start + 3 h is about when it ended, if we missed it
                first_dt = min(now, g["start"] + datetime.timedelta(hours=3))
                to_note[g["id"]] = first_dt.isoformat()
            else:
                first_dt = datetime.datetime.fromisoformat(first)
            if not pinned and now - first_dt > datetime.timedelta(hours=settings["final_hours"]):
                continue
        keep.append(g)
    order = {"in": 0, "pre": 1, "post": 2}
    keep.sort(key=lambda g: (order.get(g["state"], 3), g["start"], g["id"]))
    return keep, to_note
