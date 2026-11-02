"""Game animations for gifs mode. Every sprite is a GIF in the data folder (/data/sprite_gifs): drop one in through the web
app (or copy it there) and it is used from the next change, no restart. The name is the file name without .gif; a name
starting with "_" or "." is ignored. Standard library only: a small GIF decoder is included.

A GIF can be any size. 16x16 is used as is; a bigger one is shrunk to fit (a block of pixels becomes one, taking its
commonest colour, so the 16x-magnified GIFs the sprite importer writes come back exactly); a smaller one is centred.
Black is the unlit LED and transparent pixels are black. The Pixoo takes one frame time for the whole animation, so
frame times are rounded to a multiple of the shortest one (a frame held 3x as long is sent 3 times), and an animation of
more than MAX_FRAMES frames is thinned out."""
import os

N = 16
MAX_FRAMES = 16     # frames per upload: the Pixoo takes one HTTP request per frame
MIN_MS = 40         # the shortest frame time sent
DEFAULT_MS = 100    # a GIF frame with a delay of 10 ms or less (browsers do the same)
BLACK = (0, 0, 0)
GIF_DIR = None    # set by configure(): the folder the GIFs live in


def configure(directory):
    global GIF_DIR
    GIF_DIR = directory
    os.makedirs(directory, exist_ok=True)


def seed(source, directory):
    """Copy the shipped GIFs into the (persistent) folder the first time it is empty."""
    import shutil
    if os.path.isdir(source) and not names():
        for f in os.listdir(source):
            if f.lower().endswith(".gif"):
                shutil.copy(os.path.join(source, f), os.path.join(directory, f))


def names():
    """Sprite names, i.e. the GIF files in GIF_DIR (sorted)."""
    try:
        files = os.listdir(GIF_DIR) if GIF_DIR else []
    except OSError:
        return []
    return sorted(f[:-4] for f in files if f.lower().endswith(".gif") and not f.startswith(("_", ".")))


def build(name):
    """Return (frames, ms per frame) for the named sprite: frames are 16x16 lists of (r, g, b) rows."""
    with open(os.path.join(GIF_DIR, name + ".gif"), "rb") as f:
        width, height, images = decode_gif(f.read())
    frames = [to_screen(canvas, width, height) for canvas, _ in images]
    return resample(frames, [ms for _, ms in images])


def lzw(data, min_code):
    """Decode GIF's variable-width LZW into a bytearray of palette indexes."""
    clear, eoi = 1 << min_code, (1 << min_code) + 1
    size, nxt = min_code + 1, eoi + 1
    table = [bytes([i]) for i in range(clear)] + [b"", b""]
    out, prev, buf, nbits = bytearray(), None, 0, 0
    for byte in data:
        buf |= byte << nbits
        nbits += 8
        while nbits >= size:
            code, buf, nbits = buf & ((1 << size) - 1), buf >> size, nbits - size
            if code == clear:
                size, nxt, table, prev = min_code + 1, eoi + 1, table[:eoi + 1], None
                continue
            if code == eoi:
                return out
            if prev is None:
                entry = table[code]
            else:
                entry = table[code] if code < len(table) else prev + prev[:1]
                if nxt < 4096:
                    table.append(prev + entry[:1])
                    nxt += 1
                    if nxt == (1 << size) and size < 12:
                        size += 1
            out += entry
            prev = entry
    return out


def decode_gif(data):
    """Parse a GIF into (width, height, [(canvas, ms), ...]): one fully composited canvas per frame, each a list of
    rows of (r, g, b) or None (transparent)."""
    if data[:3] != b"GIF":
        raise ValueError("not a GIF")
    width, height, flags = int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little"), data[10]
    pos = 13
    palette = []
    if flags & 0x80:
        n = 3 * (2 << (flags & 7))
        palette = [tuple(data[pos + i:pos + i + 3]) for i in range(0, n, 3)]
        pos += n
    canvas = [[None] * width for _ in range(height)]
    images, gce = [], {"ms": DEFAULT_MS, "transparent": None, "disposal": 0}
    while pos < len(data):
        block = data[pos]
        pos += 1
        if block == 0x3B:                                       # trailer
            break
        if block == 0x21:                                       # extension
            label = data[pos]
            pos += 1
            if label == 0xF9:                                   # graphic control: delay, transparent colour, disposal
                packed = data[pos + 1]
                delay = int.from_bytes(data[pos + 2:pos + 4], "little") * 10
                gce = {"ms": delay if delay > 10 else DEFAULT_MS, "transparent": data[pos + 4] if packed & 1 else None,
                       "disposal": (packed >> 2) & 7}
            while data[pos]:                                    # skip the sub-blocks
                pos += data[pos] + 1
            pos += 1
        elif block == 0x2C:                                     # image
            left, top = int.from_bytes(data[pos:pos + 2], "little"), int.from_bytes(data[pos + 2:pos + 4], "little")
            w, h = int.from_bytes(data[pos + 4:pos + 6], "little"), int.from_bytes(data[pos + 6:pos + 8], "little")
            packed = data[pos + 8]
            pos += 9
            local = palette
            if packed & 0x80:
                n = 3 * (2 << (packed & 7))
                local = [tuple(data[pos + i:pos + i + 3]) for i in range(0, n, 3)]
                pos += n
            min_code = data[pos]
            pos += 1
            chunks = bytearray()
            while data[pos]:
                chunks += data[pos + 1:pos + 1 + data[pos]]
                pos += data[pos] + 1
            pos += 1
            pixels = lzw(bytes(chunks), min_code)
            rows = list(range(h))
            if packed & 0x40:                                   # interlaced: rows come in four passes
                rows = [r for start, step in ((0, 8), (4, 8), (2, 4), (1, 2)) for r in range(start, h, step)]
            before = [row[:] for row in canvas] if gce["disposal"] == 3 else None
            for i, y in enumerate(rows):
                if not 0 <= top + y < height:
                    continue
                for x in range(w):
                    k = i * w + x
                    if k < len(pixels) and pixels[k] != gce["transparent"] and pixels[k] < len(local) and 0 <= left + x < width:
                        canvas[top + y][left + x] = local[pixels[k]]
            images.append(([row[:] for row in canvas], gce["ms"]))
            if gce["disposal"] == 2:                            # clear this frame's rectangle
                for y in range(top, min(height, top + h)):
                    for x in range(left, min(width, left + w)):
                        canvas[y][x] = None
            elif before is not None:                            # back to how it was before this frame
                canvas = before
            gce = {"ms": DEFAULT_MS, "transparent": None, "disposal": 0}
        else:
            raise ValueError("bad GIF block 0x%02x" % block)
    if not images:
        raise ValueError("GIF has no frames")
    return width, height, images


def to_screen(canvas, width, height):
    """A decoded canvas as a 16x16 frame: shrunk to fit (commonest lit colour per block) or centred if smaller."""
    f = min(1.0, N / max(width, height))
    nw, nh = max(1, round(width * f)), max(1, round(height * f))
    out = [[BLACK] * N for _ in range(N)]
    ox, oy = (N - nw) // 2, (N - nh) // 2
    for y in range(nh):
        ya, yb = int(y / f), max(int(y / f) + 1, int((y + 1) / f))
        for x in range(nw):
            xa, xb = int(x / f), max(int(x / f) + 1, int((x + 1) / f))
            block = [canvas[yy][xx] for yy in range(ya, min(yb, height)) for xx in range(xa, min(xb, width))]
            lit = [p for p in block if p and p != BLACK]
            if block and len(lit) / len(block) >= 0.4:
                out[oy + y][ox + x] = max(set(lit), key=lit.count)
    return out


def resample(frames, delays):
    """One frame time for the whole animation: the shortest delay, with longer frames repeated; thinned to MAX_FRAMES."""
    step = max(MIN_MS, min(delays))
    counts = [max(1, round(d / step)) for d in delays]
    if sum(counts) > MAX_FRAMES:                                # too long: a coarser step, and drop frames if still too many
        step = max(step, sum(delays) / MAX_FRAMES)
        counts = [max(1, round(d / step)) for d in delays]
    seq = [f for f, c in zip(frames, counts) for _ in range(c)]
    if len(seq) > MAX_FRAMES:
        seq = [seq[int(i * len(seq) / MAX_FRAMES)] for i in range(MAX_FRAMES)]
    return seq, int(step)
