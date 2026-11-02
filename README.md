# pixoo-display

Runs a **Divoom Pixoo 16** (16×16 Wi-Fi LED display) as a clock with outdoor weather, a loop of today's sports scores, and old-school
game animations. One Docker container, a web app to control it, and optional Home Assistant entities. It needs nothing but the
Pixoo's IP address: no Home Assistant, no accounts, no API keys.

## Run it

```
cp .env.example .env     # set PIXOO_HOST (the Pixoo's IP) and TZ
docker compose up -d --build
```

To put it on another machine over SSH instead (rsync + `docker compose up -d --build` there), use `./deploy.sh user@host [folder]`;
the host keeps its own `.env` and `.env.secret`.

The optional `.env.secret` (only for the Home Assistant MQTT password) may be left out. GitHub Actions builds the image on every push
(`.github/workflows/docker.yml`) and publishes it as `ghcr.io/rodneyshupe/pixoo-display:latest`, so `docker compose pull` works too once
you are logged in to the registry.

Then open `http://<host>:8017`. Give the Pixoo a fixed IP (DHCP reservation) and set `PIXOO_HOST` to it.

## What it does

- **Clock**: time and the outdoor temperature with a weather icon, from [Open-Meteo](https://open-meteo.com/) (free, no key). Search for
  your city on the web app's Clock tab.
- **Games**: ESPN's public scoreboards (NFL, NHL, NBA, WNBA, MLB, MLS, NWSL, Premier League, Champions League, Europa League, La Liga,
  Bundesliga, Serie A, Ligue 1, college football and basketball) and the CFL's stats API (ESPN has no current CFL data). Pick any
  game of any day, or follow a team and its game each day is added. Only the current day's games are cycled, live ones first. Soccer
  lists the home team first ("VAN v SEA"), the North American leagues the away team first ("SEA @ VAN"). Team colours can be changed
  by clicking a team's letters.
- **Animations**: the GIFs in the data folder (`sprite_gifs/`), any size, shrunk to 16×16. Reorder them and switch them on and off in
  the web app, or drop a new GIF in and it is picked up.

- **Countdown**: days, hours or minutes left to any dates you add (a one-off, or yearly for birthdays and holidays). Each shows a short
  name frame, then the number at twice the size. One upload when the number changes (daily, hourly, then each minute).
- **Visualizer**: the Pixoo's own music visualizer (it listens with its own microphone and draws itself). The service only picks the
  style (the device does not say how many it has, so the Music tab offers a number of buttons you can change), lets you name and star
  styles, and can cycle through the stars.
- **Timer**: the Pixoo's own timer tool (counts down on screen and beeps). Start, pause, resume and cancel from the web app, Home
  Assistant or `POST /api/timer {"action": "start", "minutes": 5, "seconds": 0}`; the usual programme comes back after it ends.

The modes (Clock / Games / Animations / Countdown / Visualizer) are switched in the web app; a timer or a drawing shows over the
current mode and then hands back. All settings are saved in `/data/settings.json`.

## How the Pixoo is driven

The Pixoo only redraws an upload when its channel is re-selected, which flashes its loading screen for about 40 ms. So the service
sends one multi-frame animation (every selected game, each held for the seconds-per-game setting as repeated 2-second frames) and
**uploads again only when something changed** (a score, a game starting or ending, your picks). Notes from testing: a frame time over
about 2 s is not honoured (4000 → 2 s, 8000 → under 1 s, 15000 → about 3 s), so frames are 2 s; 36 frames per upload was tested.

## Drawing API (show something on the Pixoo from anything that can POST JSON)

The service keeps a 16×16 frame buffer. Paint into it, then show it. A shown drawing stays for `seconds` (default 30; `0` = until
cleared) and then the normal programme (clock, games, animations) resumes by itself. All calls are `POST` with a JSON body, and all
accept `"push": false` (paint only, show later) and `"seconds"`. Colours are `r`, `g`, `b` (0-255).

| Call | Body |
|---|---|
| `/api/draw/fill` | `{"r": 255, "g": 0, "b": 0}` (clears the buffer to that colour) |
| `/api/draw/text` | `{"text": "OK!", "x": 1, "y": 1, "r": 255, "g": 255, "b": 255}` (3×5 font, 4 characters per row, rows at y=1 and y=9 give two lines) |
| `/api/draw/rectangle` | `{"x1": 0, "y1": 9, "x2": 15, "y2": 14, "g": 255, "fill": true}` |
| `/api/draw/pixel` | `{"x": 3, "y": 4, "r": 255}` |
| `/api/draw/clear` | `{}` (empties the buffer and goes back to the normal programme now) |

```
curl -X POST http://<host>:8017/api/draw/fill -H 'Content-Type: application/json' -d '{"r":255,"g":0,"b":0,"seconds":10}'
```

For Home Assistant, ready-made `rest_command` entries for these calls (`pixoo_fill`, `pixoo_draw_text`, `pixoo_draw_rect`,
`pixoo_draw_pixel`, `pixoo_draw_clear`) are in `homeassistant/rest_commands.yaml`; replace `HOST` with this machine's address.

## Home Assistant (optional)

If `MQTT_HOST` is set the service publishes Home Assistant entities by MQTT discovery under one device, "Pixoo 16": **Display** (a light:
on/off and brightness 1-100), mode, temperature units, seconds per game / per city, a switch per followed team and per league,
"Add a game" / "Remove a game" for today's games, "Now showing", "Games in rotation" and "Display online". Nothing to configure in Home Assistant beyond its MQTT integration. `homeassistant/pixoo-dashboard.json`
is a ready-made dashboard (paste it into a new dashboard's raw configuration editor; replace `HOST` in its web-app button). Without MQTT everything works from the web app.

The MQTT user needs the permission to publish and subscribe under `pixoo16/#` and `homeassistant/#`.

## Layout

- `app/pixoo_display/`: the service (Python standard library, plus `paho-mqtt` for Home Assistant).
  `games.py` (feeds and choosing games), `render.py` (the pictures), `device.py` (talking to the Pixoo), `engine.py` (what to show),
  `web.py` + `static/index.html` (the web app), `mqttbridge.py` (Home Assistant), `weather.py`, `sprites.py` (GIF reader), `store.py` (settings).
- `seed_gifs/`: the animations copied into the data folder the first time it is empty.
- `homeassistant/`: the optional dashboard.

The feeds are unofficial and may change; a league that fails shows its error in the web app and keeps its last data.

## About the starter animations

`seed_gifs/` holds animated GIFs of classic arcade characters (Pac-Man, Galaga, Dig Dug, Frogger and others), cut from fan-ripped sprite sheets
and shrunk to 16×16. Those characters belong to their publishers: this is for personal use, so keep the repository private, or delete
`seed_gifs/` and add your own GIFs in the web app before making it public.
