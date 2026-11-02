"""Settings that come from the environment (the stack's .env). Everything the user changes while it runs lives in store.py."""
import datetime
import os
from zoneinfo import ZoneInfo


def env(key, default=""):
    v = os.environ.get(key)
    return default if v is None or v == "" else v


TZ = ZoneInfo(env("TZ", "UTC"))
PIXOO_HOST = env("PIXOO_HOST")                    # the Pixoo's IP address
DRY_RUN = env("PIXOO_DRY_RUN") == "1" or not PIXOO_HOST   # no device: build and serve frames only (development, or PIXOO_HOST not set yet)
PUBLIC_URL = env("PUBLIC_URL")                    # optional: this web app's address, shown as the link on the Home Assistant device
DATA_DIR = env("DATA_DIR", "/data")
PORT = int(env("PORT", "8017"))
MQTT_HOST = env("MQTT_HOST")                      # empty: no Home Assistant entities (the service needs nothing from HA)
MQTT_PORT = int(env("MQTT_PORT", "1883"))
MQTT_USER = env("MQTT_USER")
MQTT_PASSWORD = env("MQTT_PASSWORD")


def now():
    """Timezone-aware 'now' in the configured zone."""
    return datetime.datetime.now(TZ)
