"""Outdoor weather for the clock from Open-Meteo (free, no account or key): https://open-meteo.com/. The location is a setting
(web app, Clock tab); the place search uses Open-Meteo's geocoding."""
import json
import urllib.parse
import urllib.request

FORECAST = ("https://api.open-meteo.com/v1/forecast?latitude=%s&longitude=%s"
            "&current=temperature_2m,weather_code,is_day,wind_speed_10m&timezone=auto")
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search?name=%s&count=6&language=en&format=json"
WINDY_KMH = 45

# WMO weather code -> the condition names the icons are drawn for (render.ICONS)
CODES = {0: "sunny", 1: "sunny", 2: "partlycloudy", 3: "cloudy", 45: "fog", 48: "fog",
         51: "rainy", 53: "rainy", 55: "rainy", 56: "snowy-rainy", 57: "snowy-rainy",
         61: "rainy", 63: "rainy", 65: "pouring", 66: "snowy-rainy", 67: "snowy-rainy",
         71: "snowy", 73: "snowy", 75: "snowy", 77: "snowy", 80: "rainy", 81: "rainy", 82: "pouring",
         85: "snowy", 86: "snowy", 95: "lightning", 96: "lightning-rainy", 99: "lightning-rainy"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "pixoo-display"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)


def condition(code, is_day, wind_kmh):
    cond = CODES.get(code, "cloudy")
    if cond == "sunny" and not is_day:
        cond = "clear-night"
    elif cond == "partlycloudy" and not is_day:
        cond = "cloudy"                                  # the partly-cloudy icon has a sun
    elif cond in ("sunny", "clear-night", "cloudy", "partlycloudy") and wind_kmh >= WINDY_KMH:
        cond = "windy"
    return cond


def current(lat, lon):
    """(temperature in C, condition name, IANA time zone) right now at that place."""
    d = _get(FORECAST % (lat, lon))
    c = d["current"]
    return (float(c["temperature_2m"]), condition(c["weather_code"], c.get("is_day", 1), float(c.get("wind_speed_10m") or 0)),
            d.get("timezone") or "UTC")


def search(text):
    """Places matching the text: [{name, lat, lon}]."""
    out = []
    for r in _get(GEOCODE % urllib.parse.quote(text)).get("results", []):
        name = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        out.append({"name": name, "lat": round(r["latitude"], 4), "lon": round(r["longitude"], 4)})
    return out
