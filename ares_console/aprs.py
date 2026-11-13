"""APRS-IS client and APRS position parser."""
import re
import socket
import threading
import time

from .db import now
from .events import bus

VERSION = "ARES-Console 1.0"


# ------------------------------------------------------------------ parsing

def _base91(s):
    v = 0
    for ch in s:
        v = v * 91 + (ord(ch) - 33)
    return v


def _uncompressed(p):
    # DDMM.mmN/DDDMM.mmW$  (ambiguity spaces allowed)
    m = re.match(r"(\d{2})([\d ]{2}\.[\d ]{2})([NnSs])(.)(\d{3})([\d ]{2}\.[\d ]{2})([EeWw])(.)", p)
    if not m:
        return None
    lat = int(m.group(1)) + float(m.group(2).replace(" ", "0")) / 60.0
    if m.group(3).upper() == "S":
        lat = -lat
    lon = int(m.group(5)) + float(m.group(6).replace(" ", "0")) / 60.0
    if m.group(7).upper() == "W":
        lon = -lon
    return {"lat": lat, "lon": lon, "symbol": m.group(4) + m.group(8), "comment": p[19:]}


def _compressed(p):
    if len(p) < 13:
        return None
    try:
        lat = 90 - _base91(p[1:5]) / 380926.0
        lon = -180 + _base91(p[5:9]) / 190463.0
    except Exception:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon, "symbol": p[0] + p[9], "comment": p[13:]}


def _position(p):
    if not p:
        return None
    if p[0].isdigit():
        return _uncompressed(p)
    if p[0] in "/\\" or p[0].isalpha():
        return _compressed(p)
    return None


def _mic_e(dest, info):
    dest = dest.split("-")[0]
    if len(dest) < 6 or len(info) < 9:
        return None
    digits = []
    for ch in dest[:6]:
        if ch.isdigit():
            digits.append(ord(ch) - 48)
        elif "A" <= ch <= "J":
            digits.append(ord(ch) - 65)
        elif "P" <= ch <= "Y":
            digits.append(ord(ch) - 80)
        elif ch in "KLZ":
            digits.append(0)
        else:
            return None
    lat = digits[0] * 10 + digits[1] + (digits[2] * 10 + digits[3] + (digits[4] * 10 + digits[5]) / 100.0) / 60.0
    north = "P" <= dest[3] <= "Z"
    lon_off = 100 if "P" <= dest[4] <= "Z" else 0
    west = "P" <= dest[5] <= "Z"
    if not north:
        lat = -lat
    d = ord(info[1]) - 28 + lon_off
    if 180 <= d <= 189:
        d -= 80
    elif 190 <= d <= 199:
        d -= 190
    m = ord(info[2]) - 28
    if m >= 60:
        m -= 60
    h = ord(info[3]) - 28
    lon = d + (m + h / 100.0) / 60.0
    if west:
        lon = -lon
    sp = (ord(info[4]) - 28) * 10 + (ord(info[5]) - 28) // 10
    dc = ((ord(info[5]) - 28) % 10) * 100 + (ord(info[6]) - 28)
    if sp >= 800:
        sp -= 800
    if dc >= 400:
        dc -= 400
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return {"lat": lat, "lon": lon, "symbol": info[8] + info[7], "course": dc,
            "speed": int(sp * 1.852), "comment": info[9:]}


def parse_packet(line):
    """Return dict(callsign, lat, lon, symbol, comment, ...) or None."""
    if ">" not in line or ":" not in line:
        return None
    head, info = line.split(":", 1)
    src, rest = head.split(">", 1)
    dest = rest.split(",")[0]
    if not info:
        return None
    t = info[0]
    pos = None
    name = src
    try:
        if t == "}":
            return parse_packet(info[1:])
        if t in "!=":
            pos = _position(info[1:])
        elif t in "/@":
            pos = _position(info[8:])
        elif t in "`'\x1c\x1d":
            pos = _mic_e(dest, info)
        elif t == ";" and len(info) > 18:
            name = info[1:10].strip()
            pos = _position(info[18:])
            if pos is not None:
                pos["object_of"] = src
        elif t == ")":
            m = re.match(r"\)([^!_]{3,9})[!_](.*)", info)
            if m:
                name = m.group(1).strip()
                pos = _position(m.group(2))
        else:
            i = info.find("!")
            if 0 < i < 40:
                pos = _position(info[i + 1:])
    except (IndexError, ValueError):
        return None
    if not pos:
        return None
    pos["callsign"] = name.upper()
    pos["raw"] = line
    pos["comment"] = (pos.get("comment") or "").strip()[:120]
    return pos


# ------------------------------------------------------------------ grid / location helpers

def maidenhead_to_latlon(g):
    g = g.strip()
    if not re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2}(\d{2})?)?", g):
        return None
    g = g.upper()
    lon = (ord(g[0]) - 65) * 20 - 180
    lat = (ord(g[1]) - 65) * 10 - 90
    lon += int(g[2]) * 2
    lat += int(g[3])
    w, h = 2.0, 1.0
    if len(g) >= 6:
        w, h = 2.0 / 24, 1.0 / 24
        lon += (ord(g[4]) - 65) * w
        lat += (ord(g[5]) - 65) * h
    if len(g) >= 8:
        w, h = w / 10, h / 10
        lon += int(g[6]) * w
        lat += int(g[7]) * h
    return lat + h / 2, lon + w / 2


def latlon_to_maidenhead(lat, lon):
    lon += 180
    lat += 90
    s = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    lon %= 20
    lat %= 10
    s += str(int(lon // 2)) + str(int(lat // 1))
    lon %= 2
    lat %= 1
    s += chr(97 + int(lon * 12)) + chr(97 + int(lat * 24))
    return s


def parse_location(text):
    """Turn a free-text location (grid square or 'lat, lon') into coordinates."""
    if not text:
        return None
    t = text.strip()
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)", t)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    return maidenhead_to_latlon(t)


def base_call(c):
    return (c or "").upper().split("-")[0].strip()


# ------------------------------------------------------------------ APRS-IS client

class APRSIS(threading.Thread):
    def __init__(self, db):
        super().__init__(daemon=True, name="aprs-is")
        self.db = db
        self.sock = None
        self.status = "stopped"
        self.lock = threading.Lock()
        self.current_filter = None
        self.stop_flag = False
        self.restart_flag = False
        self.last_packet = None
        self.packets = 0

    def set_status(self, s):
        self.status = s
        bus.publish("aprs_status", {"status": s, "packets": self.packets, "filter": self.current_filter})

    def wanted_filter(self):
        calls = set()
        net = self.db.active_net()
        if net:
            for r in self.db.q("SELECT callsign FROM checkins WHERE net_id=? AND track=1", (net["id"],)):
                if r["callsign"]:
                    calls.add(base_call(r["callsign"]))
        parts = []
        if calls:
            parts.append("b/" + "/".join(sorted(c + "*" for c in calls if re.fullmatch(r"[A-Z0-9]+", c))))
        extra = self.db.get("aprs_extra_filter").strip()
        if extra:
            parts.append(extra)
        return " ".join(parts) or "b/NOCALL-99"

    def refresh_filter(self):
        f = self.wanted_filter()
        with self.lock:
            if self.sock and f != self.current_filter:
                try:
                    self.sock.sendall(("#filter %s\r\n" % f).encode())
                    self.current_filter = f
                    self.set_status("connected")
                except OSError:
                    pass

    def restart(self):
        self.restart_flag = True
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass

    def run(self):
        while not self.stop_flag:
            if self.db.get("aprs_enabled") != "1":
                self.set_status("disabled")
                time.sleep(3)
                continue
            try:
                self._session()
            except Exception as e:  # noqa
                self.set_status("error: %s" % e)
            with self.lock:
                self.sock = None
            if self.restart_flag:
                self.restart_flag = False
                continue
            time.sleep(15)

    def _session(self):
        host = self.db.get("aprs_server") or "rotate.aprs2.net"
        port = int(self.db.get("aprs_port") or 14580)
        mycall = (self.db.get("mycall") or "N0CALL").upper()
        passcode = self.db.get("aprs_passcode") or "-1"
        self.set_status("connecting to %s" % host)
        s = socket.create_connection((host, port), timeout=20)
        s.settimeout(90)
        f = self.wanted_filter()
        login = "user %s pass %s vers %s filter %s\r\n" % (mycall, passcode, VERSION, f)
        s.sendall(login.encode())
        with self.lock:
            self.sock = s
            self.current_filter = f
        self.set_status("connected")
        self.refresh_filter()  # roster may have changed while we were connecting
        buf = b""
        last_ka = time.time()
        while not self.stop_flag and not self.restart_flag:
            try:
                d = s.recv(4096)
            except socket.timeout:
                d = b"#"
            if not d:
                raise ConnectionError("server closed connection")
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.handle(line.decode("latin-1").strip())
            if time.time() - last_ka > 60:
                s.sendall(b"#keepalive\r\n")
                last_ka = time.time()

    def handle(self, line):
        if not line or line.startswith("#"):
            return
        self.packets += 1
        p = parse_packet(line)
        if not p:
            return
        self.last_packet = now()
        record_position(self.db, p["callsign"], p["lat"], p["lon"], "APRS",
                        symbol=p.get("symbol"), comment=p.get("comment"),
                        course=p.get("course"), speed=p.get("speed"), raw=p.get("raw"))


def record_position(db, callsign, lat, lon, source, symbol=None, comment=None, course=None, speed=None, raw=None):
    ts = now()
    db.x("""INSERT INTO stations (callsign, lat, lon, ts, source, symbol, comment, course, speed, raw)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(callsign) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, ts=excluded.ts,
            source=excluded.source, symbol=COALESCE(excluded.symbol, stations.symbol),
            comment=COALESCE(excluded.comment, stations.comment), course=excluded.course,
            speed=excluded.speed, raw=excluded.raw""",
         (callsign, lat, lon, ts, source, symbol, comment, course, speed, raw))
    db.insert("track", {"callsign": callsign, "lat": lat, "lon": lon, "ts": ts, "source": source})
    bus.publish("position", {"callsign": callsign, "lat": lat, "lon": lon, "ts": ts, "source": source,
                             "symbol": symbol, "comment": comment, "course": course, "speed": speed})
