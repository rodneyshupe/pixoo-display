"""Drawing for the Pixoo 16: fonts, weather icons, the clock + weather frame and the score frame. Pure functions, no I/O.

A frame is 16 rows of 16 (r, g, b) tuples; black is the unlit LED."""
import datetime

SIZE = 16
ICON_Y = 1        # top row of the icon (text and icon share rows 1-5)
TEMP_Y = 1        # top row of the temperature digits
CLOCK_Y = 10      # top row of the clock

# 3x5 font: each glyph is 5 rows of '#'/'.' (width = row length); the advance is width + 1.
G = {
    "0": ["###", "#.#", "#.#", "#.#", "###"], "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["##.", "..#", ".#.", "#..", "###"], "3": ["##.", "..#", ".#.", "..#", "##."],
    "4": ["#.#", "#.#", "###", "..#", "..#"], "5": ["###", "#..", "##.", "..#", "##."],
    "6": [".##", "#..", "###", "#.#", "###"], "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"], "9": ["###", "#.#", "###", "..#", "##."],
    "A": [".#.", "#.#", "###", "#.#", "#.#"], "B": ["##.", "#.#", "##.", "#.#", "##."],
    "C": [".##", "#..", "#..", "#..", ".##"], "D": ["##.", "#.#", "#.#", "#.#", "##."],
    "E": ["###", "#..", "##.", "#..", "###"], "F": ["###", "#..", "##.", "#..", "#.."],
    "G": [".##", "#..", "#.#", "#.#", ".##"], "H": ["#.#", "#.#", "###", "#.#", "#.#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"], "J": ["..#", "..#", "..#", "#.#", ".#."],
    "K": ["#.#", "#.#", "##.", "#.#", "#.#"], "L": ["#..", "#..", "#..", "#..", "###"],
    "M": ["#.#", "###", "###", "#.#", "#.#"], "N": ["##.", "#.#", "#.#", "#.#", "#.#"],
    "O": [".#.", "#.#", "#.#", "#.#", ".#."], "P": ["##.", "#.#", "##.", "#..", "#.."],
    "Q": [".#.", "#.#", "#.#", "###", ".##"], "R": ["##.", "#.#", "##.", "#.#", "#.#"],
    "S": [".##", "#..", ".#.", "..#", "##."], "T": ["###", ".#.", ".#.", ".#.", ".#."],
    "U": ["#.#", "#.#", "#.#", "#.#", "###"], "V": ["#.#", "#.#", "#.#", "#.#", ".#."],
    "W": ["#.#", "#.#", "###", "###", "#.#"], "X": ["#.#", "#.#", ".#.", "#.#", "#.#"],
    "Y": ["#.#", "#.#", ".#.", ".#.", ".#."], "Z": ["###", "..#", ".#.", "#..", "###"],
    ":": [".", "#", ".", "#", "."], "-": ["...", "...", "###", "...", "..."],
    " ": ["...", "...", "...", "...", "..."], ".": [".", ".", ".", ".", "#"], ",": [".", ".", ".", "#", "#"],
    "!": ["#", "#", "#", ".", "#"], "?": ["##.", "..#", ".#.", "...", ".#."], "/": ["..#", "..#", ".#.", "#..", "#.."],
    "%": ["#.#", "..#", ".#.", "#..", "#.#"], "+": ["...", ".#.", "###", ".#.", "..."], "=": ["...", "###", "...", "###", "..."],
    "*": ["...", "#.#", ".#.", "#.#", "..."], "_": ["...", "...", "...", "...", "###"], "'": ["#", "#", ".", ".", "."],
    "(": [".#", "#.", "#.", "#.", ".#"], ")": ["#.", ".#", ".#", ".#", "#."], "#": ["#.#", "###", "#.#", "###", "#.#"],
    "<": ["..#", ".#.", "#..", ".#.", "..#"], ">": ["#..", ".#.", "..#", ".#.", "#.."], "@": [".##", "#.#", "###", "#..", ".##"],
}

# 4x4 weather icons. Palette: Y sun yellow, M moon, W light cloud, D dark cloud, B rain blue, S snow white,
# C wind/hail cyan, R red; '.' is off.
PALETTE = {
    "Y": (255, 200, 0), "M": (230, 230, 150), "W": (190, 190, 205), "D": (110, 110, 130), "B": (40, 110, 255),
    "S": (255, 255, 255), "C": (0, 200, 255), "R": (255, 30, 30),
}
ICONS = {
    "sunny": [".YY.", "YYYY", "YYYY", ".YY."],
    "clear-night": [".MM.", "MM..", "MM..", ".MM."],
    "cloudy": ["....", ".WW.", "WWWW", "WWWW"],
    "partlycloudy": ["Y...", ".WW.", "WWWW", "WWWW"],
    "rainy": [".WW.", "WWWW", "B.B.", ".B.B"],
    "pouring": ["DDDD", "B.B.", ".B.B", "B.B."],
    "snowy": [".WW.", "WWWW", "S.S.", ".S.S"],
    "snowy-rainy": [".WW.", "WWWW", "B.S.", ".S.B"],
    "hail": [".DD.", "DDDD", "C.C.", ".C.C"],
    "lightning": [".DD.", "DDDD", "..Y.", ".Y.."],
    "lightning-rainy": [".DD.", "DDDD", "B.Y.", ".YB."],
    "fog": ["WWWW", "....", "WWWW", "...."],
    "windy": ["CCC.", "...C", "CCCC", "...."],
    "exceptional": [".RR.", ".RR.", "....", ".RR."],
}
ICONS["windy-variant"] = ICONS["windy"]


def temp_colour(t):
    """Colour for the outdoor temperature (deg C)."""
    if t is None:
        return (160, 160, 160)
    for limit, rgb in ((0, (80, 120, 255)), (10, (0, 220, 255)), (20, (0, 255, 80)), (27, (255, 160, 0))):
        if t < limit:
            return rgb
    return (255, 40, 40)


def text_width(text):
    return sum(len(G.get(c, G[" "])[0]) + 1 for c in text) - 1 if text else 0


def blit(frame, text, x, y, rgb):
    """Draw text into frame with its top-left at x, y; clipped to the frame. A character with no glyph is left blank."""
    for ch in text:
        g = G.get(ch, G[" "])
        for dy, row in enumerate(g):
            for dx, bit in enumerate(row):
                px, py = x + dx, y + dy
                if bit == "#" and 0 <= px < SIZE and 0 <= py < SIZE:
                    frame[py][px] = rgb
        x += len(g[0]) + 1


def blit_big(frame, text, x, y, rgb, scale=2):
    """Digits (and letters) drawn `scale` times as large."""
    for ch in text:
        g = G.get(ch, G[" "])
        for dy, row in enumerate(g):
            for dx, bit in enumerate(row):
                if bit == "#":
                    for sy in range(scale):
                        for sx in range(scale):
                            px, py = x + dx * scale + sx, y + dy * scale + sy
                            if 0 <= px < SIZE and 0 <= py < SIZE:
                                frame[py][px] = rgb
        x += (len(g[0]) + 1) * scale


def big_width(text, scale=2):
    return sum((len(G.get(c, G[" "])[0]) + 1) * scale for c in text) - scale if text else 0


def countdown_units(seconds):
    """(number, unit text) for the time left: days from two days out, then hours, then minutes."""
    if seconds >= 2 * 86400:
        return str(int(seconds // 86400)), "DAYS"
    if seconds >= 2 * 3600:
        return str(int(seconds // 3600)), "HRS"
    if seconds >= 60:
        return str(int(seconds // 60)), "MIN"
    return "0", "NOW"


def build_countdown_label(code, rgb):
    """First picture of a countdown: its short name across the top, 'LEFT' below."""
    f = blank_frame()
    code = code[:4]
    blit(f, code, (SIZE - text_width(code)) // 2, 2, rgb)
    blit(f, "LEFT", (SIZE - text_width("LEFT")) // 2, 9, (200, 200, 200))
    return f


def build_countdown_number(number, unit, rgb):
    """Second picture: the number big (twice the size up to two digits) and its unit beneath."""
    f = blank_frame()
    scale = 2 if len(number) <= 2 else 1
    top = 1 if scale == 2 else 3
    blit_big(f, number, (SIZE - big_width(number, scale)) // 2, top, rgb, scale)
    blit(f, unit, (SIZE - text_width(unit)) // 2, 11, (200, 200, 200))
    return f


def build_visualizer_preview(style):
    """A stand-in picture of coloured equaliser bars, for the web app (the real visualizer is drawn by the Pixoo itself)."""
    f = blank_frame()
    heights = [(3 + (style * 5 + i * 7) % 11) for i in range(8)]
    for i, h in enumerate(heights):
        for y in range(h):
            row = 15 - y
            colour = (0, 220, 80) if y < 7 else (255, 200, 0) if y < 10 else (255, 50, 50)
            for x in (i * 2, i * 2 + 1):
                f[row][x] = colour
    return f


def build_timer_preview(seconds):
    """The remaining time as M:SS (MMSS from ten minutes), for the web app; the Pixoo draws its own."""
    f = blank_frame()
    m, s = divmod(max(0, int(seconds)), 60)
    text = "%d:%02d" % (m, s) if m < 10 else "%02d%02d" % (m, s)
    blit(f, text, (SIZE - text_width(text)) // 2, 5, (255, 200, 60))
    for x in range(0, SIZE):
        f[12][x] = (60, 60, 60)
    return f


def blank_frame():
    return [[(0, 0, 0)] * SIZE for _ in range(SIZE)]


def draw_text(frame, text, x, y, rgb):
    """Free text for the drawing API: the 3x5 font, lower case drawn as upper case, up to 4 characters per row."""
    blit(frame, text.upper(), x, y, rgb)


def draw_rect(frame, x1, y1, x2, y2, rgb, fill=True):
    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))
    for y in range(max(0, y1), min(SIZE - 1, y2) + 1):
        for x in range(max(0, x1), min(SIZE - 1, x2) + 1):
            if fill or x in (x1, x2) or y in (y1, y2):
                frame[y][x] = rgb


def draw_icon(frame, condition):
    art = ICONS.get(condition, ICONS["exceptional"] if condition else ICONS["cloudy"])
    for y, row in enumerate(art):
        for x, ch in enumerate(row):
            if ch != ".":
                frame[ICON_Y + y][x] = PALETTE[ch]


def draw_clock(frame, now):
    """HH:MM in 16 px: hour digits at x=0 and 4, colon at 7, minute digits at x=9 and 13 (digits are 3 wide)."""
    hh, mm = "%02d" % now.hour, "%02d" % now.minute
    rgb = (255, 255, 255)
    blit(frame, hh[0], 0, CLOCK_Y, rgb)
    blit(frame, hh[1], 4, CLOCK_Y, rgb)
    blit(frame, ":", 7, CLOCK_Y, (120, 120, 120))
    blit(frame, mm[0], 9, CLOCK_Y, rgb)
    blit(frame, mm[1], 13, CLOCK_Y, rgb)


def temp_text(temp_c, units="C"):
    """'6C' / '43F' / '--' for no reading; whole degrees."""
    if temp_c is None:
        return "--"
    v = int(round(temp_c * 9 / 5 + 32 if units == "F" else temp_c))
    return "%d%s" % (0 if v == 0 else v, "F" if units == "F" else "C")


def build_frame(temp_c, condition, now, units="C"):
    """Weather icon and temperature on the top half, the time (of `now`, which may be in another time zone) below."""
    f = [[(0, 0, 0)] * SIZE for _ in range(SIZE)]
    draw_icon(f, condition)
    text = temp_text(temp_c, units)
    blit(f, text, SIZE - text_width(text), TEMP_Y, temp_colour(temp_c))   # right-aligned beside the icon
    draw_clock(f, now)
    return f


def city_code(name):
    """A short code for a place name, up to 3 letters: 'Vancouver, BC' -> VAN, 'New York' -> NY, 'Los Angeles' -> LA."""
    words = [w for w in "".join(c if c.isalpha() or c == " " else " " for c in name.split(",")[0]).split() if w]
    code = "".join(w[0] for w in words) if len(words) > 1 else (words[0][:3] if words else "?")
    return code.upper()[:3]


def build_city_frame(code, now):
    """Which city the next frames are about: its code across the top half, the time below as in the weather frame."""
    f = [[(0, 0, 0)] * SIZE for _ in range(SIZE)]
    code = "".join(c for c in code.upper() if c.isalnum() and c in G)[:3] or "?"
    blit(f, code, (SIZE - text_width(code)) // 2, TEMP_Y + 1, (120, 200, 255))
    draw_clock(f, now)
    return f


def rgb_of(hex_colour):
    try:
        return tuple(int(hex_colour[i:i + 2], 16) for i in (0, 2, 4))
    except (TypeError, ValueError):
        return None


def luminance(rgb):
    return 0.3 * rgb[0] + 0.59 * rgb[1] + 0.11 * rgb[2]


def team_colour(primary, alternate=None):
    """ESPN team colour for the black background: the primary, or the alternate when the primary is too dark (navy
    teams: Seahawks -> green, Bears -> orange). Only if both are dark is the primary lightened."""
    p, a = rgb_of(primary), rgb_of(alternate)
    if p and luminance(p) >= 70:
        return p
    if a and luminance(a) >= 70:
        return a
    r, g, b = p or a or (255, 255, 255)
    for _ in range(8):
        if luminance((r, g, b)) >= 110:
            break
        r, g, b = (c + (255 - c) // 3 for c in (r, g, b))
    return (r, g, b)


def listing(game):
    """(first side, second side, separator) in the order the sport lists a game: soccer puts the home team first
    ("VAN v SEA"), the North American leagues put the away team first ("SEA @ VAN")."""
    if game.get("sport") == "soccer":
        return game["home"], game["away"], "v"
    return game["away"], game["home"], "@"


def progress(game):
    """How far through a live game, 0..1: soccer by the minute (of 90), everything else by period / periods."""
    if game.get("sport") == "soccer":
        digits = "".join(ch for ch in str(game.get("clock") or "").split("'")[0] if ch.isdigit())
        return min(1.0, int(digits) / 90) if digits else game["period"] / game["periods"]
    return game["period"] / max(1, game["periods"])


def needs_split(game):
    """A three-digit score (basketball) is 11 pixels wide, leaving room for a single letter on a 16-pixel row."""
    return game["state"] != "pre" and max(game["away"]["score"], game["home"]["score"]) >= 100


def _status_bar(f, game):
    if game["state"] == "in":
        n, colour = max(1, min(SIZE, round(SIZE * progress(game)))), (255, 40, 40)
    else:
        n, colour = SIZE, (160, 160, 160)
    for x in range(n):
        f[13][x] = f[14][x] = colour


def build_scores_frame(game):
    """Second picture of a game with a three-digit score (the longer one): each team's first letter on the left, its score beside it."""
    f = [[(0, 0, 0)] * SIZE for _ in range(SIZE)]
    first, second, _ = listing(game)
    leader = max(first["score"], second["score"])
    for side, y in ((first, 1), (second, 7)):
        text = str(side["score"])
        rgb = (255, 255, 255) if game["state"] == "in" or side["score"] == leader else (120, 120, 120)
        blit(f, text, SIZE - text_width(text), y, rgb)
        blit(f, side["abbr"][:1], 0, y, side["colour"])
    _status_bar(f, game)
    return f


def build_names_frame(game):
    """First picture of a game with a three-digit score, shown for 2 s: the three-letter names, whose first letters stay where the score picture has them."""
    f = [[(0, 0, 0)] * SIZE for _ in range(SIZE)]
    first, second, _ = listing(game)
    for side, y in ((first, 1), (second, 7)):
        blit(f, side["abbr"][:3], 0, y, side["colour"])
    _status_bar(f, game)
    return f


def score_pictures(game, now):
    """The pictures one game is made of: one normally (the names and the scores: 3 letters while both scores are one digit, else 2);
    with a three-digit score, which leaves room for only one letter beside it, two: the 3-letter names (2 s), then first letters + scores."""
    if needs_split(game):
        return [build_names_frame(game), build_scores_frame(game)]
    return [build_score_frame(game, now)]


def build_score_frame(game, now):
    f = [[(0, 0, 0)] * SIZE for _ in range(SIZE)]
    first, second, _ = listing(game)
    if game["state"] == "pre":
        # Two-letter codes side by side (in listing order), then the start time (or the weekday when it is not today) below.
        blit(f, first["abbr"][:2], 0, 1, first["colour"])
        blit(f, second["abbr"][:2], SIZE - text_width(second["abbr"][:2]), 1, second["colour"])
        start = game["start"]
        if start.date() != now.date():
            text = start.strftime("%a").upper()
        else:
            h12 = start.hour % 12 or 12
            text = "%d:%02d" % (h12, start.minute) if h12 < 10 else "%d%02d" % (h12, start.minute)
        blit(f, text, (SIZE - text_width(text)) // 2, 8, (200, 200, 200))
        for x in range(0, SIZE, 4):
            f[14][x] = f[14][x + 1] = (80, 80, 80)
        return f
    leader = max(first["score"], second["score"])
    letters = 3 if leader < 10 else 2          # three letters fit beside a one-digit score, two beside a two-digit one
    for side, y in ((first, 1), (second, 7)):
        score = str(side["score"])
        rgb = (255, 255, 255) if game["state"] == "in" or side["score"] == leader else (120, 120, 120)
        blit(f, score, SIZE - text_width(score), y, rgb)
        blit(f, side["abbr"][:letters], 0, y, side["colour"])
    if game["state"] == "in":   # red bar: how far through the game, at least a dot
        n = max(1, min(SIZE, round(SIZE * progress(game))))
        colour = (255, 40, 40)
    else:                       # final: a full grey bar
        n, colour = SIZE, (160, 160, 160)
    for x in range(n):
        f[13][x] = f[14][x] = colour
    return f
