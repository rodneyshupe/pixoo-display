# pixoo-display

Turn a **Divoom Pixoo 16** (the 16×16 Wi-Fi LED display) into a clock with weather for several cities, a loop of today's sports scores,
countdowns, a timer, the Pixoo's own music visualizer, and your own pixel-art animations. It is one Docker container with a web app to
control it, and it can optionally show up in Home Assistant. It needs nothing but the Pixoo's IP address: no accounts, no API keys.

> **This project is vibe coded.** It was written almost entirely by an AI assistant ([Claude Code](https://claude.com/claude-code)) from
> plain-English requests, with a human steering, testing every change on a real Pixoo and reading the results, rather than writing it
> line by line. It works well for its author, but it has only ever run on **one Pixoo 16** and one home network, it has no automated
> tests, and it reads unofficial web feeds. Read the code before you trust it with anything that matters. It is provided as is, under the
> [MIT licence](LICENSE).

## What you need

- A **Divoom Pixoo 16** on your Wi-Fi (2.4 GHz). Other Pixoo models use a different picture size and will not work as they are.
- A machine that is always on and can run Docker with Compose (a Raspberry Pi, a NAS, a home server, a VM).
- The Pixoo's **IP address**. Give it a fixed address (a DHCP reservation in your router), then it never changes.
- Internet access on that machine (weather and scores).

## Quick start

```
git clone https://github.com/rodneyshupe/pixoo-display.git
cd pixoo-display
cp .env.example .env          # then edit .env: PIXOO_HOST (the Pixoo's IP), TZ (your time zone), and APPDATA_ROOT (see below)
docker compose up -d --build
```

`APPDATA_ROOT` is the folder where the service keeps its [settings and animations](#persistent-storage-and-settings): the default `/srv/appdata`
is fine on a Linux server; on a Mac or a laptop pick any folder you can keep, such as `/Users/you/pixoo-data`.

Open **http://\<that machine\>:8017**. You should see the "Now showing" picture, and the Pixoo should switch to its custom channel and show
the clock. If the page says "Pixoo offline", check `PIXOO_HOST` (see [Troubleshooting](#troubleshooting)). Without `PIXOO_HOST` the app
still starts, in a "no device" mode, so you can look around the web app first.

The web app has **no login**: keep it on your home network and do not expose port 8017 to the internet.

## Using it

The picture at the top shows what is on the Pixoo now. The buttons under it switch the **mode**, and the tabs below hold each mode's settings.

| Mode | What the Pixoo shows | Where you set it up |
|---|---|---|
| **Clock** | The weather icon and temperature on top, the time below. With several cities it cycles through them, each with its own local time. | **Clock** tab: search for a city to add it; drag or ▲▼ to reorder; untick to skip one; °C or °F; seconds per city. |
| **Games** | Today's scores, one after another: live games first, then games still to come, then recent finals. | **Sports** tab (below). |
| **Animations** | Your GIFs, one after another. | **Animations** tab: drag to reorder, untick to skip, upload new GIFs (any size; they are shrunk to 16×16). |
| **Countdown** | Days, hours or minutes left to dates you add, one after another, each as a short name then a big number. | **Countdown** tab: name, date and time, colour, "every year" for birthdays and holidays. |
| **Visualizer** | The Pixoo's own music visualizer: it listens with its own microphone and draws itself. | **Music** tab: click a style, name it, star favourites, optionally cycle through the stars. |

Beside the modes:

- **Timer** (the **Timer** tab): the Pixoo's own timer. It counts down on screen and beeps at zero, then the usual programme comes back.
- **Display on/off and brightness**: the On/Off switch and the brightness slider in the "Now showing" panel at the top of the page.
- **Drawing API**: show your own picture or text for a while from any script (see below).

### Setting up the sports

1. **Sports** tab → **Games**. It lists every game today in the leagues that are switched on. Use ‹ › or the date box to look at any other day.
2. **Tick a game** to add it to the rotation (it plays on the day it is played), or **click a ☆** next to a team to *follow* it: that team's game
   is then added automatically every day it plays.
3. Switch leagues on or off under **Leagues** (NFL, CFL, NHL, NBA, WNBA, MLB, MLS, NWSL, Premier League, Champions League, Europa League, La Liga,
   Bundesliga, Serie A, Ligue 1, college football and basketball). Only the current day's games are ever cycled.
4. Click a team's letters to change its colour (some feeds give none, or a poor one). **Seconds per game** sets how long each game is held.
5. Scores of one digit show three-letter team names, two digits show two letters, and three digits (basketball) alternate a short names
   picture with the scores. Soccer lists the home team first ("VAN v SEA"); the North American leagues list the away team first ("SEA @ VAN").

## Persistent storage and settings

**Everything you set in the web app is kept in one folder, the *data folder*, and nothing else needs saving.** In the container it is
`/data`, and `compose.yaml` maps it to a folder on the host:

```yaml
    volumes:
      - ${APPDATA_ROOT}/pixoo-display:/data      # APPDATA_ROOT comes from .env, e.g. /srv/appdata
```

So with `APPDATA_ROOT=/srv/appdata` the data lives in `/srv/appdata/pixoo-display/` on the host. The folder is created on first start, the
container runs as root so no permissions need setting up, and it survives `docker compose down`, rebuilds and upgrades. **Keep this folder
(and back it up): if it is lost the service starts again with the defaults.**

What is in it:

| Path | What it is |
|---|---|
| `settings.json` | Every setting: mode, brightness and display on/off, cities and units, followed teams, leagues, team colours, picked games, countdowns, timer, visualizer style names and favourites, and the order of the animations. Written whenever you change something. |
| `sprite_gifs/` | The animation GIFs. On the very first start, if this folder is empty, the starter set from `seed_gifs/` is copied in. After that the folder is yours: add, delete or rename GIFs here or in the web app, and a new GIF is picked up without a restart. A file name starting with `_` or `.` is ignored. |

Not saved (rebuilt on its own): the game feeds, the weather, and any drawing from the drawing API.

**Settings that come from the environment instead** (the `.env` file, read when the container starts; change them and run `docker compose up -d`):

| Variable | Default | What it does |
|---|---|---|
| `PIXOO_HOST` | none | The Pixoo's IP address. Required; without it the app runs without a device. |
| `TZ` | `UTC` | Your time zone, for the clock and for which games count as "today". |
| `APPDATA_ROOT` | none (set in `.env`) | The host folder that holds the data folder. |
| `PORT` | `8017` | The web app's port. |
| `PUBLIC_URL` | none | Optional: the web app's address, shown as a link on the Home Assistant device. |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER` | none, `1883`, none | Optional Home Assistant entities (below). Leave `MQTT_HOST` empty to turn them off. |
| `MQTT_PASSWORD` | none | In `.env.secret` (git-ignored), not `.env`. |

**Back up, restore, move, reset**

```
# back up
tar czf pixoo-display-backup.tgz -C /srv/appdata pixoo-display
# restore, or move to another machine: stop the container, unpack into the same place, start it
docker compose down && tar xzf pixoo-display-backup.tgz -C /srv/appdata && docker compose up -d
# reset the settings only (the animations stay)
docker compose down && rm /srv/appdata/pixoo-display/settings.json && docker compose up -d
```

Stop the container before editing `settings.json` by hand, because the service rewrites it.

**Without Compose**, mount the data folder yourself, or the settings will vanish when the container is replaced:

```
docker build -t pixoo-display .
docker run -d --name pixoo-display --restart unless-stopped -p 8017:8017 \
  -e PIXOO_HOST=192.168.1.50 -e TZ=America/Vancouver \
  -v /srv/appdata/pixoo-display:/data pixoo-display
```

A Docker named volume works the same way (`-v pixoo-display-data:/data`); then back it up with `docker run --rm -v pixoo-display-data:/data -v "$PWD":/b alpine tar czf /b/backup.tgz -C /data .`.

## Home Assistant (optional)

Everything works without it. If you use Home Assistant and have the **MQTT** integration set up, the service can appear there as one device,
**Pixoo 16**, with no YAML to write:

1. Create an MQTT user for it on your broker (for Mosquitto: `mosquitto_passwd`), and note the broker's address.
2. In `.env` set `MQTT_HOST` (and `MQTT_USER`); in `.env.secret` put `MQTT_PASSWORD=...`. Run `docker compose up -d`.
3. The entities appear by MQTT discovery: **Display** (a light: on/off and brightness), mode, temperature units, seconds per game / city /
   countdown, a switch per followed team and per league, "Add a game" / "Remove a game" for today's games, timer minutes with **Start / Pause /
   Cancel** buttons and a timer sensor, visualizer style and cycle, "Now showing", "Games in rotation" and "Display online".

`homeassistant/pixoo-dashboard.json` is a ready-made dashboard (paste it into a new dashboard's raw configuration editor and replace `HOST`
in its web-app button). The MQTT user needs permission to publish and subscribe under `pixoo16/#` and `homeassistant/#`.

## Drawing API

The service keeps a 16×16 frame buffer. Paint into it, then show it. A shown drawing stays for `seconds` (default 30; `0` = until cleared) and
then the normal programme resumes by itself. All calls are `POST` with a JSON body, and all accept `"push": false` (paint only, show later) and
`"seconds"`. Colours are `r`, `g`, `b` (0-255).

| Call | Body |
|---|---|
| `/api/draw/fill` | `{"r": 255, "g": 0, "b": 0}` (clears the buffer to that colour) |
| `/api/draw/text` | `{"text": "OK!", "x": 1, "y": 1, "r": 255, "g": 255, "b": 255}` (3×5 font, 4 characters per row; rows at y=1 and y=9 give two lines) |
| `/api/draw/rectangle` | `{"x1": 0, "y1": 9, "x2": 15, "y2": 14, "g": 255, "fill": true}` |
| `/api/draw/pixel` | `{"x": 3, "y": 4, "r": 255}` |
| `/api/draw/clear` | `{}` (empties the buffer and goes back to the normal programme now) |

```
curl -X POST http://<host>:8017/api/draw/fill -H 'Content-Type: application/json' -d '{"r":255,"g":0,"b":0,"seconds":10}'
curl -X POST http://<host>:8017/api/timer     -H 'Content-Type: application/json' -d '{"action":"start","minutes":5,"seconds":0}'
```

`homeassistant/rest_commands.yaml` has ready-made Home Assistant `rest_command` entries for the drawing calls (replace `HOST`).

## Updating

```
git pull && docker compose up -d --build
```

To deploy to another machine over SSH (rsync, then `docker compose up -d --build` there; the host keeps its own `.env` and `.env.secret`), use
`./deploy.sh user@host [folder]`. GitHub Actions also builds the image on every push and publishes it as `ghcr.io/rodneyshupe/pixoo-display`;
if you cannot pull it, `docker compose up -d --build` builds it from this source instead.

## Troubleshooting

- **"Pixoo offline" in the web app**: check `PIXOO_HOST`; the Pixoo must be on the same network as the container and answer at `http://<ip>/post`
  (`curl -X POST http://<ip>/post -d '{"Command":"Channel/GetIndex"}'` should answer). The Pixoo only does 2.4 GHz Wi-Fi.
- **The Pixoo drops off Wi-Fi and only a reboot brings it back**: seen on the author's unit and reported by other owners, usually after its access point changes channel. Use a
  fixed 2.4 GHz channel (1, 6 or 11) at 20 MHz on its access point, with WPA2.
- **A brief flash of a loading screen when the picture changes**: the Pixoo only redraws an upload when its channel is re-selected. The service
  uploads only when something changed to keep this rare.
- **No games shown**: check the **Sports** tab, that the league is on, that `TZ` is right, and the red error line under the games list (a league
  whose feed failed shows its error there and keeps its last data).
- **Weather missing ("--")**: the machine needs internet access to open-meteo.com; pick a city on the **Clock** tab.
- **Home Assistant entities missing**: `MQTT_HOST`, user and password; look at `docker compose logs pixoo-display` for "MQTT connected".

## How the Pixoo is driven

The service talks to the Pixoo's own local HTTP API (`POST http://<ip>/post`, JSON "Command"s). Notes from testing on one unit: it redraws a custom
upload only after its channel is re-selected (about 40 ms of loading screen); a frame time over about 2 s is not honoured (4000 gave 2 s, 8000
under 1 s, 15000 about 3 s), so a game is held as several 2-second frames; 36 frames in one upload worked; a frame ID it already has is ignored,
so each upload takes the next ID. Many commands accept any value without an error, so a command that "worked" is not proof it did anything.

## Layout

- `app/pixoo_display/`: the service (Python standard library, plus `paho-mqtt` for Home Assistant): `games.py` (feeds and choosing games),
  `render.py` (the pictures), `device.py` (talking to the Pixoo), `engine.py` (what to show), `web.py` + `static/index.html` (the web app),
  `mqttbridge.py` (Home Assistant), `weather.py`, `sprites.py` (GIF reader), `store.py` (saved settings).
- `seed_gifs/`: the starter animations. `homeassistant/`: the optional dashboard and commands. `deploy.sh`: copy to a host over SSH.

## Data sources and credits

Weather: [Open-Meteo](https://open-meteo.com/) (free, no key). Scores: ESPN's public scoreboard feeds and the CFL's own stats API (ESPN has no current
CFL data). Both are unofficial and may change or stop without notice. The Pixoo's local API is Divoom's. This project is not affiliated with
Divoom, ESPN or the CFL.

### About the starter animations

`seed_gifs/` holds animated GIFs of classic arcade characters (Pac-Man, Galaga, Dig Dug, Frogger and others), cut from fan-ripped sprite sheets and
shrunk to 16×16, as a starter set for the animations mode. The characters belong to their publishers and these GIFs are **not** covered by this
project's MIT licence: they are included for personal use. If that matters to you, delete `seed_gifs/` (or just the ones you don't want) and
add your own GIFs in the web app; nothing else depends on them.

## Licence

[MIT](LICENSE) © 2026 Rodney Shupe. The software is provided as is, without warranty.
