"""Home Assistant entities over MQTT discovery (the broker on ha-radio, .24). Everything shows up under one device, "Pixoo 16":

  select   Mode (Clock / Games / Animations)        number  Seconds per game, Minutes per animation, Hours to keep finals
  switch   Show <team> games, one per followed team (follow more in the web app)
  select   Add a game / Remove a game               today's games; choosing one adds or removes it, then the box resets
  sensor   Now showing, Games in rotation           binary_sensor  Display online

Discovery messages are retained, so HA keeps the entities across its own restarts; the entities go "unavailable" if this
service stops (last-will message). Teams that are removed in the web app have their switch removed from HA.
"""
import datetime
import json
import re
import threading

import paho.mqtt.client as mqtt

from . import config, games as gm, render, web

BASE = "pixoo16"
DISCOVERY = "homeassistant"
NONE = "—"
MODE_LABELS = {"clock": "Clock", "scores": "Games", "gifs": "Animations", "countdown": "Countdown", "visualizer": "Visualizer"}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def game_label(g):
    first, second, sep = render.listing(g)
    return "%s: %s %s %s, %s" % (g["league_name"], first["abbr"], sep, second["abbr"],
                                 {"pre": g["start"].strftime("%-I:%M %p"), "in": "live", "post": "final"}[g["state"]])


class Bridge:
    def __init__(self, app, log=print):
        self.app, self.log = app, log
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pixoo-display")
        self.client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
        self.client.will_set("%s/availability" % BASE, "offline", retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.wake = threading.Event()
        self.published = {}          # topic -> last payload sent (state topics)
        self.discovered = {}         # discovery topic -> last config sent
        self.game_ids = {"add": {}, "remove": {}}   # label -> game id, for the two game selects
        app.store.listeners.append(self.wake.set)

    # ---- connection
    def start(self):
        self.client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=30)
        self.client.loop_start()
        threading.Thread(target=self.loop, daemon=True, name="mqtt-sync").start()

    def status(self):
        return {"enabled": True, "connected": self.connected, "broker": "%s:%d" % (config.MQTT_HOST, config.MQTT_PORT)}

    def on_connect(self, client, userdata, flags, reason, properties=None):
        if reason.is_failure:
            self.log("MQTT connect refused: %s" % reason)
            return
        self.connected = True
        self.log("MQTT connected to %s:%d" % (config.MQTT_HOST, config.MQTT_PORT))
        client.subscribe([("%s/+/set" % BASE, 0), ("%s/status" % DISCOVERY, 0)])
        self.published.clear()
        self.discovered.clear()
        client.publish("%s/availability" % BASE, "online", retain=True)
        self.wake.set()

    def on_disconnect(self, client, userdata, flags, reason, properties=None):
        if self.connected:
            self.log("MQTT disconnected (%s), reconnecting" % reason)
        self.connected = False

    # ---- what HA sees
    def device(self):
        dev = {"identifiers": ["pixoo16"], "name": "Pixoo 16", "manufacturer": "Divoom", "model": "Pixoo 16"}
        if config.PUBLIC_URL:
            dev["configuration_url"] = config.PUBLIC_URL
        return dev

    def entities(self):
        """object id -> (component, discovery config, state payload, attributes or None)."""
        s = self.app.store.get()
        today, _ = self.app.games.today()
        selected, _ = gm.choose(today, s, config.now())
        selected_ids = {g["id"] for g in selected}
        now = self.app.engine.now_showing
        out = {}

        def base(obj, name, **extra):
            cfg = {"name": name, "unique_id": "pixoo16_" + obj, "device": self.device(),
                   "availability_topic": "%s/availability" % BASE}
            cfg.update(extra)
            return cfg

        out["display"] = ("light", base("display", "Display", icon="mdi:led-matrix", command_topic="%s/display/set" % BASE,
                                        state_topic="%s/display/state" % BASE, payload_on="ON", payload_off="OFF",
                                        brightness_command_topic="%s/display_brightness/set" % BASE,
                                        brightness_state_topic="%s/display_brightness/state" % BASE, brightness_scale=100),
                          ("ON" if s["screen_on"] else "OFF", str(s["brightness"] or 40)), None)
        out["mode"] = ("select", base("mode", "Mode", icon="mdi:led-matrix", options=list(MODE_LABELS.values()),
                                      command_topic="%s/mode/set" % BASE, state_topic="%s/mode/state" % BASE),
                       MODE_LABELS[s["mode"]], None)
        for obj, name, key, lo, hi, unit, icon in (("dwell", "Seconds per live game", "dwell", 4, 60, "s", "mdi:timer-sand"),
                                                    ("dwell_pre", "Seconds per upcoming game", "dwell_pre", 2, 60, "s", "mdi:timer-sand-empty"),
                                                    ("dwell_post", "Seconds per finished game", "dwell_post", 2, 60, "s", "mdi:timer-sand-complete"),
                                                    ("gif_minutes", "Minutes per animation", "gif_minutes", 1, 30, "min", "mdi:timer-outline"),
                                                    ("final_hours", "Hours to keep finals", "final_hours", 0, 12, "h", "mdi:flag-checkered"),
                                                    ("city_seconds", "Seconds per city", "city_seconds", 4, 60, "s", "mdi:city-variant-outline"),
                                                    ("countdown_seconds", "Seconds per countdown", "countdown_seconds", 4, 60, "s", "mdi:calendar-clock"),
                                                    ("vis_style", "Visualizer style", "vis_style", 0, 31, "", "mdi:equalizer"),
                                                    ("timer_minutes", "Timer minutes", "timer_minutes", 1, 99, "min", "mdi:timer-outline")):
            out[obj] = ("number", base(obj, name, icon=icon, min=lo, max=hi, step=1, unit_of_measurement=unit, mode="box",
                                       entity_category="config", command_topic="%s/%s/set" % (BASE, obj),
                                       state_topic="%s/%s/state" % (BASE, obj)), str(s[key]), None)
        for obj, name, icon in (("timer_start", "Start timer", "mdi:timer-play-outline"), ("timer_pause", "Pause or resume timer", "mdi:timer-pause-outline"),
                                ("timer_cancel", "Cancel timer", "mdi:timer-off-outline")):
            out[obj] = ("button", base(obj, name, icon=icon, command_topic="%s/%s/set" % (BASE, obj), payload_press="PRESS"), None, None)
        t = s["timer"]
        out["timer"] = ("sensor", base("timer", "Timer", icon="mdi:timer-outline", state_topic="%s/timer/state" % BASE,
                                       json_attributes_topic="%s/timer/attributes" % BASE), t["state"],
                        {"ends_at": datetime.datetime.fromtimestamp(t["end"], config.TZ).isoformat() if t["state"] == "running" else None,
                         "minutes": round(t["total"] / 60, 1), "seconds_left_when_paused": t["remaining"] if t["state"] == "paused" else None})
        out["vis_cycle"] = ("switch", base("vis_cycle", "Cycle visualizer favourites", icon="mdi:equalizer-outline", entity_category="config",
                                           command_topic="%s/vis_cycle/set" % BASE, state_topic="%s/vis_cycle/state" % BASE),
                            "ON" if s["vis_cycle"] else "OFF", None)
        out["units"] = ("select", base("units", "Temperature units", icon="mdi:thermometer", options=["Celsius", "Fahrenheit"],
                                       command_topic="%s/units/set" % BASE, state_topic="%s/units/state" % BASE),
                        "Fahrenheit" if s["units"] == "F" else "Celsius", None)
        for t in s["teams"]:
            obj = "team_" + slug(t["key"])
            out[obj] = ("switch", base(obj, "Show %s games" % t["name"], icon="mdi:star", command_topic="%s/%s/set" % (BASE, obj),
                                       state_topic="%s/%s/state" % (BASE, obj)), "ON" if t["on"] else "OFF", None)
        for key, (lname, *_rest) in gm.LEAGUES.items():
            obj = "league_" + key
            out[obj] = ("switch", base(obj, "League: %s" % lname, icon="mdi:trophy-outline", entity_category="config",
                                       command_topic="%s/%s/set" % (BASE, obj), state_topic="%s/%s/state" % (BASE, obj)),
                        "ON" if key in s["leagues"] else "OFF", None)
        add = {game_label(g): (g["id"], g["start"].date().isoformat(), web.game_name(g)) for g in today if g["id"] not in s["pins"] and g["state"] != "post"}
        remove = {game_label(g): (g["id"], None, "") for g in today if g["id"] in s["pins"]}
        self.game_ids = {"add": add, "remove": remove}
        out["add_game"] = ("select", base("add_game", "Add a game", icon="mdi:plus-circle-outline", options=[NONE] + sorted(add),
                                          command_topic="%s/add_game/set" % BASE, state_topic="%s/add_game/state" % BASE), NONE, None)
        out["remove_game"] = ("select", base("remove_game", "Remove a game", icon="mdi:minus-circle-outline", options=[NONE] + sorted(remove),
                                             command_topic="%s/remove_game/set" % BASE, state_topic="%s/remove_game/state" % BASE), NONE, None)
        out["now_showing"] = ("sensor", base("now_showing", "Now showing", icon="mdi:television-ambient-light",
                                             state_topic="%s/now_showing/state" % BASE, json_attributes_topic="%s/now_showing/attributes" % BASE),
                              (now["label"] or "Clock")[:250], {"mode": now["mode"], "games": [g["label"] for g in now.get("playlist", [])]})
        out["games_in_rotation"] = ("sensor", base("games_in_rotation", "Games in rotation", icon="mdi:scoreboard", state_class="measurement",
                                                   state_topic="%s/games_in_rotation/state" % BASE,
                                                   json_attributes_topic="%s/games_in_rotation/attributes" % BASE),
                                    str(len(selected)), {"games": [game_label(g) for g in today if g["id"] in selected_ids],
                                                         "today": len(today)})
        out["online"] = ("binary_sensor", base("online", "Display online", device_class="connectivity", entity_category="diagnostic",
                                               state_topic="%s/online/state" % BASE), "ON" if self.app.pixoo.online else "OFF", None)
        return out

    # ---- publishing
    def publish_all(self):
        entities = self.entities()
        wanted = set()
        for obj, (component, cfg, state, attrs) in entities.items():
            topic = "%s/%s/pixoo16/%s/config" % (DISCOVERY, component, obj)
            wanted.add(topic)
            cfg = dict(cfg, default_entity_id="%s.pixoo_%s" % (component, obj))    # HA 2026: replaces object_id
            payload = json.dumps(cfg, sort_keys=True)
            if self.discovered.get(topic) != payload:
                self.client.publish(topic, payload, retain=True)
                self.discovered[topic] = payload
            if component == "light":                                  # on/off on one topic, the brightness (1-100) on another
                state, bright = state
                bt = cfg["brightness_state_topic"]
                if self.published.get(bt) != bright:
                    self.client.publish(bt, bright, retain=True)
                    self.published[bt] = bright
            if component in ("select", "number", "switch", "sensor", "binary_sensor", "light"):
                st = cfg["state_topic"]
                if self.published.get(st) != state:
                    self.client.publish(st, state, retain=True)
                    self.published[st] = state
            if attrs is not None:
                at = cfg["json_attributes_topic"]
                body = json.dumps(attrs)
                if self.published.get(at) != body:
                    self.client.publish(at, body, retain=True)
                    self.published[at] = body
        for topic in [t for t in self.discovered if t not in wanted]:     # a team that was removed: drop its entity
            self.client.publish(topic, "", retain=True)
            del self.discovered[topic]

    def loop(self):
        while True:
            self.wake.wait(3)
            self.wake.clear()
            if self.connected:
                try:
                    self.publish_all()
                except Exception as e:
                    self.log("MQTT publish failed: %s: %s" % (type(e).__name__, e))

    # ---- commands from HA
    def on_message(self, client, userdata, msg):
        if msg.topic == "%s/status" % DISCOVERY:             # HA restarted: send everything again
            if msg.payload.decode() == "online":
                self.published.clear()
                self.discovered.clear()
                self.wake.set()
            return
        obj = msg.topic.split("/")[1]
        value = msg.payload.decode().strip()
        s = self.app.store
        try:
            if obj == "mode":
                s.update(mode={v: k for k, v in MODE_LABELS.items()}[value])
            elif obj == "display":
                s.update(screen_on=value == "ON")
            elif obj == "display_brightness":
                s.update(brightness=int(float(value)))
            elif obj == "timer_start":
                self.app.engine.timer_action("start", s.get()["timer_minutes"] * 60)
            elif obj == "timer_pause":
                self.app.engine.timer_action("pause" if s.get()["timer"]["state"] == "running" else "resume")
            elif obj == "timer_cancel":
                self.app.engine.timer_action("cancel")
            elif obj == "vis_cycle":
                s.update(vis_cycle=value == "ON")
            elif obj == "units":
                s.update(units="F" if value == "Fahrenheit" else "C")
            elif obj in ("dwell", "dwell_pre", "dwell_post", "gif_minutes", "final_hours", "city_seconds", "countdown_seconds", "vis_style", "timer_minutes"):
                s.update(**{obj: int(float(value))})
            elif obj.startswith("team_"):
                key = next(t["key"] for t in s.get()["teams"] if "team_" + slug(t["key"]) == obj)
                s.set_team(key, on=value == "ON")
            elif obj.startswith("league_"):
                key = obj[len("league_"):]
                if key not in gm.LEAGUES:
                    raise KeyError(key)
                s.set_league(key, value == "ON")
                self.app.games.wake.set()
            elif obj in ("add_game", "remove_game"):
                ids = self.game_ids["add" if obj == "add_game" else "remove"]
                if value in ids:
                    game_id, day, label = ids[value]
                    s.pin(game_id, obj == "add_game", day, label)
                self.published.pop("%s/%s/state" % (BASE, obj), None)    # snap the box back to "—"
        except (KeyError, ValueError, StopIteration, RuntimeError) as e:
            self.log("MQTT command %s=%r ignored: %s" % (obj, value, e))
        self.app.engine.wake.set()
        self.wake.set()
