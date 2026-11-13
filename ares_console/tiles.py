"""Offline map tiles: a caching tile proxy, MBTiles packs, and area download.

Lookup order for /tiles/{z}/{x}/{y}.png:
  1. any *.mbtiles file in <data>/tiles/        (offline packs you install)
  2. the disk cache <data>/tiles/cache/<source>/z/x/y.png
  3. the online tile server (Settings > Map tile URL); the result is cached
Every tile you look at while online is kept, so the map keeps working when the
Internet or power goes out.
"""
import glob
import hashlib
import math
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request

from .events import bus

USER_AGENT = "ARES-Console/1.0 (amateur radio emergency net control; local tile cache)"
MAX_SEED_TILES = 20000

# Map sources. "offline" says whether the provider's terms allow keeping tiles / area downloads.
# OpenStreetMap's own servers forbid bulk/offline downloading, so OSM is shown live only
# (loaded directly by the browser) and never proxied, cached or pre-downloaded here.
PRESETS = {
    "usgs_topo": {"name": "USGS Topo (US, public domain - works offline)",
                  "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}",
                  "offline": True, "max_native": 16,
                  "attribution": "USGS The National Map"},
    "usgs_imagery": {"name": "USGS Imagery + Topo (US, public domain - works offline)",
                     "url": "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}",
                     "offline": True, "max_native": 16,
                     "attribution": "USGS The National Map"},
    "osm": {"name": "OpenStreetMap (online only)",
            "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "offline": False, "max_native": 19,
            "attribution": "&copy; OpenStreetMap contributors"},
    "custom": {"name": "Custom tile server (Settings URL)", "url": None, "offline": True, "max_native": 19,
               "attribution": ""},
}


def is_osm_org(url):
    return "tile.openstreetmap.org" in (url or "")


def deg2tile(lat, lon, z):
    lat = max(min(lat, 85.0511), -85.0511)
    n = 2 ** z
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def tiles_in(bounds, zmin, zmax):
    s, w, n, e = bounds
    for z in range(zmin, zmax + 1):
        x0, y0 = deg2tile(n, w, z)
        x1, y1 = deg2tile(s, e, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                yield z, x, y


def count_tiles(bounds, zmin, zmax):
    s, w, n, e = bounds
    total = 0
    for z in range(zmin, zmax + 1):
        x0, y0 = deg2tile(n, w, z)
        x1, y1 = deg2tile(s, e, z)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


class TileCache:
    def __init__(self, db, data_dir):
        self.db = db
        self.root = os.path.join(data_dir, "tiles")
        os.makedirs(os.path.join(self.root, "cache"), exist_ok=True)
        self.offline_until = 0
        self.lock = threading.Lock()
        self.mb = {}
        self.seed = {"running": False, "done": 0, "total": 0, "failed": 0, "skipped": 0, "msg": ""}
        self.seed_cancel = False

    # ---------------------------------------------------------- sources
    def preset(self):
        key = self.db.get("map_source") or "usgs_topo"
        p = dict(PRESETS.get(key, PRESETS["usgs_topo"]))
        p["key"] = key if key in PRESETS else "usgs_topo"
        if p["key"] == "custom":
            p["url"] = self.db.get("map_tiles") or PRESETS["usgs_topo"]["url"]
        if is_osm_org(p["url"]):
            p["offline"] = False
        return p

    def source_url(self):
        return self.preset()["url"]

    def can_cache(self):
        return self.preset()["offline"]

    def cache_dir(self):
        url = self.source_url()
        tag = hashlib.sha1(url.encode()).hexdigest()[:10]
        d = os.path.join(self.root, "cache", tag)
        if not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "SOURCE.txt"), "w") as fh:
                fh.write(url + "\n")
        return d

    def _path(self, z, x, y):
        return os.path.join(self.cache_dir(), str(z), str(x), "%d.png" % y)

    def mbtiles_files(self):
        return sorted(glob.glob(os.path.join(self.root, "*.mbtiles")))

    def _mb_conn(self, path):
        c = self.mb.get(path)
        if c is None:
            c = sqlite3.connect("file:%s?mode=ro" % path, uri=True, check_same_thread=False)
            self.mb[path] = c
        return c

    def _from_mbtiles(self, z, x, y):
        tms_y = (2 ** z - 1) - y
        for p in self.mbtiles_files():
            try:
                with self.lock:
                    r = self._mb_conn(p).execute(
                        "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                        (z, x, tms_y)).fetchone()
                if r:
                    return bytes(r[0])
            except sqlite3.Error:
                continue
        return None

    # ---------------------------------------------------------- fetch
    def online(self):
        return time.time() >= self.offline_until

    def _download(self, z, x, y, timeout=6):
        url = self.source_url().replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        url = url.replace("{s}", "abc"[(x + y) % 3])
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200 or r.headers.get("X-Blocked"):
                raise PermissionError("tile server refused: %s" % (r.headers.get("X-Blocked") or r.status))
            data = r.read()
            ctype = r.headers.get("Content-Type", "")
        if not data or ("image" not in ctype and not data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1")):
            raise ValueError("not an image")
        return data

    def _store(self, z, x, y, data):
        p = self._path(z, x, y)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, p)

    def get(self, z, x, y):
        """Return (bytes, source) or (None, reason)."""
        data = self._from_mbtiles(z, x, y)
        if data:
            return data, "mbtiles"
        p = self._path(z, x, y)
        if os.path.exists(p):
            with open(p, "rb") as fh:
                return fh.read(), "cache"
        if not self.can_cache():
            return None, "online-only source"
        if not self.online():
            return None, "offline"
        try:
            data = self._download(z, x, y)
        except (urllib.error.HTTPError, PermissionError, ValueError):
            return None, "not available"  # server reachable, tile just not there / refused
        except Exception:  # noqa - network failure means "treat as offline for a bit"
            self.offline_until = time.time() + 30
            bus.publish("tiles_status", {"online": False})
            return None, "offline"
        self._store(z, x, y, data)
        if self.offline_until:
            self.offline_until = 0
            bus.publish("tiles_status", {"online": True})
        return data, "online"

    # ---------------------------------------------------------- status
    def status(self):
        d = self.cache_dir()
        n = 0
        size = 0
        for dp, _dn, fns in os.walk(d):
            for fn in fns:
                if fn.endswith(".png"):
                    n += 1
                    size += os.path.getsize(os.path.join(dp, fn))
        mbs = [{"name": os.path.basename(p), "size": os.path.getsize(p)} for p in self.mbtiles_files()]
        p = self.preset()
        return {"preset": p, "presets": {k: v["name"] for k, v in PRESETS.items()}, "cached_tiles": n, "cached_bytes": size, "cache_dir": d, "tiles_dir": self.root,
                "mbtiles": mbs, "online": self.online(), "seed": dict(self.seed), "source": self.source_url()}

    def clear(self):
        import shutil
        shutil.rmtree(self.cache_dir(), ignore_errors=True)

    # ---------------------------------------------------------- area download
    def start_seed(self, bounds, zmin, zmax):
        if self.seed["running"]:
            raise RuntimeError("An area download is already running")
        if not self.can_cache():
            raise ValueError("This map source (%s) does not allow offline downloads. Choose USGS Topo, "
                             "USGS Imagery, or your own tile server in Settings, or install an .mbtiles pack."
                             % self.preset()["name"])
        zmin, zmax = int(zmin), int(zmax)
        if not (0 <= zmin <= zmax <= 17):
            raise ValueError("Zoom range must be within 0-17")
        total = count_tiles(bounds, zmin, zmax)
        if total > MAX_SEED_TILES:
            raise ValueError("That is %d tiles; the limit is %d. Zoom in, or lower the maximum zoom."
                             % (total, MAX_SEED_TILES))
        self.seed_cancel = False
        self.seed = {"running": True, "done": 0, "total": total, "failed": 0, "skipped": 0, "msg": "starting"}
        threading.Thread(target=self._seed, args=(bounds, zmin, zmax), daemon=True).start()
        return total

    def cancel_seed(self):
        self.seed_cancel = True

    def _seed(self, bounds, zmin, zmax):
        last_pub = 0
        consecutive_fail = 0
        for z, x, y in tiles_in(bounds, zmin, zmax):
            if self.seed_cancel:
                self.seed["msg"] = "cancelled"
                break
            if os.path.exists(self._path(z, x, y)) or self._from_mbtiles(z, x, y):
                self.seed["skipped"] += 1
            else:
                try:
                    self._store(z, x, y, self._download(z, x, y, timeout=15))
                    consecutive_fail = 0
                    time.sleep(0.05)  # be polite to the tile server
                except Exception:  # noqa
                    self.seed["failed"] += 1
                    consecutive_fail += 1
                    if consecutive_fail >= 10:
                        self.seed["msg"] = "stopped: tile server unreachable"
                        break
            self.seed["done"] += 1
            if time.time() - last_pub > 0.5:
                last_pub = time.time()
                bus.publish("tiles_seed", dict(self.seed))
        else:
            self.seed["msg"] = "complete"
        self.seed["running"] = False
        bus.publish("tiles_seed", dict(self.seed))
