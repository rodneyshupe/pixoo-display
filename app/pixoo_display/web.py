"""The web app: a JSON API and one page (static/index.html). LAN only, no login (same as pixoo-rest)."""
import datetime
import json
import os
import time
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config, games as gm, render, sprites, weather

HERE = os.path.dirname(os.path.abspath(__file__))


def game_name(g):
    """'MLS VAN v SEA' / 'NFL CHI @ SEA': league, then the teams in the order the sport lists them."""
    first, second, sep = render.listing(g)
    return "%s %s %s %s" % (g["league_name"], first["abbr"], sep, second["abbr"])


def picks(app, settings):
    """The picked games, each with a readable name (looked up by id when it was saved without one) and its day."""
    out = []
    for gid, pin in settings["pins"].items():
        label = pin.get("label") or ""
        if not label:
            g = app.games.find(gid)
            if g:
                label = game_name(g)
                app.store.set_pin_label(gid, label)
        out.append({"id": gid, "day": pin["day"], "label": label or "(game not in the loaded lists)"})
    return sorted(out, key=lambda p: (p["day"], p["label"]))


def public_game(g, selected_ids, settings):
    followed = {t["key"] for t in settings["teams"] if t["on"]}
    first, second, sep = render.listing(g)

    def side(s):
        return {"abbr": s["abbr"], "key": s["key"], "name": s["name"], "score": s["score"],
                "colour": "#%02x%02x%02x" % s["colour"], "followed": s["key"] in followed}

    return {"id": g["id"], "league": g["league"], "league_name": g["league_name"], "state": g["state"], "period": g["period"],
            "periods": g["periods"], "clock": g["clock"], "detail": g["detail"], "start": g["start"].isoformat(),
            "first": side(first), "second": side(second), "sep": sep, "pinned": g["id"] in settings["pins"],
            "selected": g["id"] in selected_ids, "label": game_name(g)}


def cities_now(app, settings):
    """The saved cities, in order, each with its current weather and local time (if read yet)."""
    out = []
    for c in settings["cities"]:
        wx = app.engine.weather.get(c) or {}
        try:
            local = config.now().astimezone(ZoneInfo(wx["tz"])).strftime("%H:%M") if wx.get("tz") else None
        except Exception:
            local = None
        out.append(dict(c, on=c.get("on", True), temp=wx.get("temp"), condition=wx.get("cond"), local=local))
    return out


def timer_now(settings):
    """The timer as the page needs it: state, total, and the seconds left right now."""
    t = settings["timer"]
    left = max(0, t["end"] - time.time()) if t["state"] == "running" else t["remaining"] if t["state"] == "paused" else 0
    return {"state": t["state"], "total": t["total"], "left": round(left, 1), "ends_at": t["end"] if t["state"] == "running" else None}


def parse_day(text):
    try:
        return datetime.date.fromisoformat(text)
    except (TypeError, ValueError):
        return config.now().date()


class App:
    """What the handlers need, set by main.py."""
    store = engine = games = pixoo = mqtt = None


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pixoo-display"

        def log_message(self, *a):          # keep the container log quiet
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def _json(self):
            try:
                return json.loads(self._body() or b"{}")
            except ValueError:
                return {}

        def do_GET(self):
            path = urlparse(self.path).path
            try:
                if path in ("/", "/index.html"):
                    with open(os.path.join(HERE, "static", "index.html"), "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
                if path == "/api/health":
                    return self._send(200, {"ok": True})
                if path == "/api/state":
                    s = app.store.get()
                    rotation = [gm.colourise(g, s["colours"]) for g in gm.choose(app.games.today()[0], s, config.now())[0]]
                    return self._send(200, {
                        "settings": {k: s[k] for k in ("mode", "dwell", "gif_minutes", "final_hours", "teams", "units", "city_seconds", "screen_on", "brightness",
                                                           "countdowns", "countdown_seconds", "vis_style", "vis_styles", "vis_favourites", "vis_cycle", "vis_cycle_seconds", "vis_names", "timer_minutes")},
                        "now": app.engine.now_showing, "device": app.pixoo.status(),
                        "selected": len(rotation), "rotation": [public_game(g, {x["id"] for x in rotation}, s) for g in rotation], "sprites": sprites.names(),
                        "animations": [{"name": n, "on": on} for n, on in app.store.animations(sprites.names())],
                        "cities": cities_now(app, s), "drawing": app.engine.drawing(), "timer": timer_now(s),
                        "mqtt": app.mqtt.status() if app.mqtt else {"enabled": False},
                        "time": config.now().isoformat(),
                        "leagues": [{"key": k, "name": v[0], "on": k in s["leagues"]} for k, v in gm.LEAGUES.items()],
                        "colours": s["colours"],
                        "picks": picks(app, s)})
                if path == "/api/games":
                    day = parse_day(parse_qs(urlparse(self.path).query).get("date", [""])[0])
                    games_for_day, errors = app.games.on_day(day)
                    s = app.store.get()
                    ids = {g["id"] for g in gm.choose([gm.colourise(g, s["colours"]) for g in games_for_day], s, config.now())[0]}
                    return self._send(200, {"date": day.isoformat(), "today": config.now().date().isoformat(), "errors": errors,
                                            "games": [public_game(gm.colourise(g, s["colours"]), ids, s) for g in games_for_day]})
                if path == "/api/weather/search":
                    q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
                    return self._send(200, {"places": weather.search(q) if len(q) >= 2 else []})
                if path == "/api/sprite":
                    name = parse_qs(urlparse(self.path).query).get("name", [""])[0]
                    with open(os.path.join(sprites.GIF_DIR, os.path.basename(name) + ".gif"), "rb") as f:
                        return self._send(200, f.read(), "image/gif")
            except FileNotFoundError:
                return self._send(404, {"error": "not found"})
            except Exception as e:
                return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                if path == "/api/sprite":                       # raw GIF body; ?name=mario
                    name = os.path.basename(parse_qs(urlparse(self.path).query).get("name", [""])[0]).lower()
                    name = "".join(c for c in name if c.isalnum() or c in "-_")
                    if not name or name[0] in "_.":
                        return self._send(400, {"error": "give a name (letters, digits, - _) that does not start with _"})
                    data = self._body()
                    sprites.decode_gif(data)                      # reject anything that is not a readable GIF
                    with open(os.path.join(sprites.GIF_DIR, name + ".gif"), "wb") as f:
                        f.write(data)
                    return self._send(200, {"saved": name, "sprites": sprites.names()})
                b = self._json()
                if path == "/api/settings":
                    s = app.store.update(**{k: b[k] for k in ("mode", "dwell", "gif_minutes", "final_hours", "units", "city_seconds", "screen_on", "brightness",
                                                       "countdown_seconds", "vis_style", "vis_styles", "vis_cycle", "vis_cycle_seconds", "timer_minutes") if k in b})
                elif path == "/api/pin":
                    app.store.pin(str(b["id"]), bool(b.get("pinned", True)), b.get("day"), str(b.get("label", "")))
                elif path == "/api/league":
                    if b["key"] not in gm.LEAGUES:
                        raise ValueError("unknown league")
                    app.store.set_league(b["key"], bool(b.get("on", True)))
                    app.games.wake.set()
                elif path.startswith("/api/draw/"):          # what pixoo-rest did for Home Assistant: paint into a buffer, show it
                    op = path[len("/api/draw/"):]
                    app.engine.draw(op, b, push=bool(b.get("push", True)), seconds=max(0, int(b.get("seconds", 30))))
                elif path == "/api/timer":
                    seconds = int(b.get("minutes", 0)) * 60 + int(b.get("seconds", 0))
                    app.engine.timer_action(str(b.get("action", "start")), seconds)
                elif path == "/api/countdowns":
                    app.store.set_countdowns(b["countdowns"])
                elif path == "/api/vis/favourites":
                    app.store.set_vis_favourites(b["styles"])
                elif path == "/api/vis/name":
                    app.store.set_vis_name(b["style"], b.get("name", ""))
                elif path == "/api/cities":
                    app.store.set_cities(b["cities"])
                    app.engine.weather.wake.set()
                elif path == "/api/animations":
                    app.store.set_animations(b.get("order", []), b.get("off", []))
                elif path == "/api/colour":
                    app.store.set_colour(b["key"], b.get("colour"))
                elif path == "/api/team":
                    if b.get("remove"):
                        app.store.remove_team(b["key"])
                    else:
                        app.store.set_team(b["key"], b.get("name"), b.get("on", True))
                elif path == "/api/sprite/delete":
                    name = os.path.basename(str(b.get("name", "")))
                    os.remove(os.path.join(sprites.GIF_DIR, name + ".gif"))
                else:
                    return self._send(404, {"error": "not found"})
                app.engine.wake.set()
                return self._send(200, {"ok": True})
            except (KeyError, ValueError, TypeError) as e:
                return self._send(400, {"error": str(e)})
            except RuntimeError as e:
                return self._send(502, {"error": str(e)})
            except FileNotFoundError:
                return self._send(404, {"error": "not found"})
            except Exception as e:
                return self._send(500, {"error": "%s: %s" % (type(e).__name__, e)})

    return Handler


def serve(app, port):
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
    server.serve_forever()
