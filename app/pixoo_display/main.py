import os
import sys
import threading

from . import config, sprites
from .device import Pixoo
from .engine import Engine
from .games import GamesService
from .store import Store
from .web import App, serve


def log(msg):
    print("%s %s" % (config.now().isoformat(timespec="seconds"), msg), file=sys.stderr, flush=True)


def main():
    app = App()
    app.store = Store()
    sprites.configure(os.path.join(config.DATA_DIR, "sprite_gifs"))
    sprites.seed(config.env("SEED_GIFS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "seed_gifs")), sprites.GIF_DIR)
    app.games = GamesService(app.store)
    app.pixoo = Pixoo(config.PIXOO_HOST, config.DRY_RUN, log)
    app.engine = Engine(app.store, app.games, app.pixoo, log)
    app.mqtt = None
    if config.MQTT_HOST:
        from .mqttbridge import Bridge
        app.mqtt = Bridge(app, log)
        app.mqtt.start()
    app.games.start()
    app.engine.start()
    if not config.PIXOO_HOST:
        log("PIXOO_HOST is not set: running without a device (the web app works, nothing is sent). Set it in .env.")
    log("pixoo-display up: web :%d, Pixoo %s%s, %d sprites, mode %s" % (
        config.PORT, config.PIXOO_HOST, " (dry run)" if config.DRY_RUN else "", len(sprites.names()), app.store.get()["mode"]))
    serve(app, config.PORT)
