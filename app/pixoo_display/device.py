"""The Pixoo itself: send it frames, but only when the picture changed.

The Pixoo only redraws a custom-channel upload when the channel is re-selected first (it shows its loading screen
until the upload lands, about 40 ms), so a change is: get the next gif id, select channel 3, send the frames. Things
that do not work: uploading without re-selecting (accepted, never shown), selecting after the upload (stays on the
loading screen), a frame time over ~2 s (capped), and a frame ID the device already has (ignored).
"""
import base64
import hashlib
import json
import threading
import time
import urllib.error
import urllib.request

from . import config
from .render import SIZE

MAX_PIC_ID = 30          # the device's gif id counter is reset before it gets here
CHECK_EVERY = 60         # seconds between "still on the custom channel?" checks while the picture is unchanged
RETRY_EVERY = 10         # seconds between attempts while the Pixoo does not answer


class Pixoo:
    def __init__(self, host, dry_run=False, log=print):
        self.host, self.dry_run, self.log = host, dry_run, log
        self.lock = threading.Lock()
        self.digest = None
        self.checked = 0.0
        self.failed_at = 0.0
        self.online = None               # None until the first contact
        self.error = ""
        self.since = time.time()         # when `online` last changed
        self.sent = 0                    # uploads so far (for the status page)
        self.power_applied = None        # (screen on, brightness) last given to the device; None = send again (it just came back)
        self.device_brightness = None    # what the device itself reported
        self.visualizer = None           # the visualizer style last set (None: not on the visualizer)

    def _post(self, payload):
        req = urllib.request.Request("http://%s/post" % self.host, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            res = json.load(r)
        if res.get("error_code") != 0:
            raise RuntimeError("Pixoo error for %s: %s" % (payload.get("Command"), res))
        return res

    def _prepare(self, frames, speed):
        pic_id = self._post({"Command": "Draw/GetHttpGifId"}).get("PicId", 1)
        if pic_id >= MAX_PIC_ID:
            self._post({"Command": "Draw/ResetHttpGifId"})
            pic_id = 1
        pic_id = max(pic_id, 1)
        return [{"Command": "Draw/SendHttpGif", "PicNum": len(frames), "PicWidth": SIZE, "PicOffset": i, "PicID": pic_id,
                 "PicSpeed": speed, "PicData": base64.b64encode(bytes(c for row in f for px in row for c in px)).decode()}
                for i, f in enumerate(frames)]

    def _set_online(self, ok, error=""):
        if ok and not self.online:
            self.power_applied = None                          # a Pixoo that just came back may have lost its brightness
        if ok != self.online:
            self.since = time.time()
            if ok and self.online is False:
                self.log("Pixoo %s is back" % self.host)
            elif not ok:
                self.log("Pixoo %s unreachable or failing (retrying every %d s, silent until it recovers): %s" % (self.host, RETRY_EVERY, error))
        self.online, self.error = ok, error

    def show(self, frames, speed, force=False):
        """Make the Pixoo show these frames (a list of 16x16 frames, `speed` ms each). Returns True if it was sent."""
        digest = hashlib.sha1(json.dumps([frames, speed]).encode()).hexdigest()
        with self.lock:
            now = time.time()
            if self.dry_run:
                if digest != self.digest:
                    self.digest, self.sent = digest, self.sent + 1
                self._set_online(True)
                return True
            if self.failed_at and now - self.failed_at < RETRY_EVERY:
                return False
            try:
                if digest == self.digest and not force:
                    if now - self.checked < CHECK_EVERY:
                        return False
                    self.checked = now
                    if self._post({"Command": "Channel/GetIndex"}).get("SelectIndex") == 3:   # still showing our channel
                        self._set_online(True)
                        return False
                sends = self._prepare(frames, speed)
                self._post({"Command": "Channel/SetIndex", "SelectIndex": 3})
                for req in sends:                                  # one frame per request: PicNum is the total, PicOffset the index
                    self._post(req)
            except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
                self.failed_at, self.checked = now, 0.0     # check straight away once it answers again
                self._set_online(False, str(e))
                return False
            self.failed_at, self.checked, self.visualizer = 0.0, now, None
            self.digest, self.sent = digest, self.sent + 1
            self._set_online(True)
            return True

    def ensure_visualizer(self, style):
        """Put the Pixoo on its music visualizer with this style (choosing a style also switches to that channel). Sent when the style
        changes, after the device comes back, and whenever a minutely check finds it on another channel."""
        with self.lock:
            now = time.time()
            if self.dry_run:
                self.visualizer, self.digest = style, None
                return
            if self.failed_at and now - self.failed_at < RETRY_EVERY:
                return
            try:
                if self.visualizer == style and now - self.checked < CHECK_EVERY:
                    return
                self.checked = now
                if self.visualizer == style and self._post({"Command": "Channel/GetIndex"}).get("SelectIndex") == 2:
                    self._set_online(True)
                    return
                self._post({"Command": "Channel/SetEqPosition", "EqPosition": int(style)})
            except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
                self.failed_at, self.checked, self.visualizer = now, 0.0, None
                self._set_online(False, str(e))
                return
            self.failed_at, self.visualizer = 0.0, style
            self.digest = None                                 # whatever comes next has to be uploaded again
            self._set_online(True)

    def timer(self, seconds, run=True):
        """Start (or stop) the Pixoo's own timer tool: it shows the countdown itself and beeps at zero. Returns True if it answered."""
        if self.dry_run:
            return True
        with self.lock:
            try:
                self._post({"Command": "Tools/SetTimer", "Minute": int(seconds) // 60, "Second": int(seconds) % 60, "Status": 1 if run else 0})
            except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
                self._set_online(False, str(e))
                return False
            self.digest, self.visualizer = None, None          # whatever shows afterwards has to be sent again
            return True

    def read_brightness(self):
        """The device's own brightness (1-100), or None if it does not answer."""
        if self.dry_run:
            return 40
        with self.lock:
            try:
                self.device_brightness = int(self._post({"Command": "Channel/GetAllConf"})["Brightness"])
            except (urllib.error.URLError, OSError, RuntimeError, ValueError, KeyError):
                return None
        return self.device_brightness

    def apply_power(self, on, brightness):
        """Give the device the screen state and brightness wanted, but only when they differ from what it was last given
        (or it has just come back)."""
        want = (bool(on), brightness)
        with self.lock:
            if want == self.power_applied:
                return
            if self.dry_run:
                self.power_applied = want
                return
            if self.failed_at and time.time() - self.failed_at < RETRY_EVERY:
                return
            try:
                if brightness is not None:
                    self._post({"Command": "Channel/SetBrightness", "Brightness": int(brightness)})
                self._post({"Command": "Channel/OnOffScreen", "OnOff": 1 if on else 0})
            except (urllib.error.URLError, OSError, RuntimeError, ValueError) as e:
                self.failed_at, self.checked = time.time(), 0.0
                self._set_online(False, str(e))
                return
            self.power_applied = want
            self._set_online(True)

    def status(self):
        return {"online": self.online, "error": self.error, "since": self.since, "uploads": self.sent, "host": self.host,
                "dry_run": self.dry_run}
