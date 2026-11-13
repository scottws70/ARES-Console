"""JS8Call TCP API client (enable in JS8Call: Settings > Reporting > TCP Server API)."""
import json
import socket
import threading
import time

from .aprs import maidenhead_to_latlon, record_position, base_call
from .db import now
from .events import bus


class JS8(threading.Thread):
    def __init__(self, db):
        super().__init__(daemon=True, name="js8")
        self.db = db
        self.sock = None
        self.status = "stopped"
        self.lock = threading.Lock()
        self.restart_flag = False
        self.info = {}

    def set_status(self, s):
        self.status = s
        bus.publish("js8_status", {"status": s, "info": self.info})

    def restart(self):
        self.restart_flag = True
        with self.lock:
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass

    def run(self):
        while True:
            if self.db.get("js8_enabled") != "1":
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
            for _ in range(20):  # retry in 10 s, sooner if restart() is called
                if self.restart_flag:
                    break
                time.sleep(0.5)
            self.restart_flag = False

    def send_raw(self, typ, value="", params=None):
        msg = {"type": typ, "value": value, "params": params or {"_ID": int(time.time() * 1000)}}
        with self.lock:
            if not self.sock:
                raise ConnectionError("JS8Call not connected")
            self.sock.sendall((json.dumps(msg) + "\n").encode())

    def connected(self):
        return self.sock is not None and self.status == "connected"

    def set_freq(self, dial_hz=None, offset_hz=None):
        params = {"_ID": int(time.time() * 1000)}
        if dial_hz is not None:
            params["DIAL"] = int(dial_hz)
        if offset_hz is not None:
            params["OFFSET"] = int(offset_hz)
        self.send_raw("RIG.SET_FREQ", "", params)
        self.request_freq()

    def request_freq(self):
        self._last_poll = time.time()
        try:
            self.send_raw("RIG.GET_FREQ")
        except (ConnectionError, OSError):
            pass

    def maybe_poll(self):
        if self.connected() and time.time() - getattr(self, "_last_poll", 0) > 2:
            self.request_freq()

    def send_message(self, text):
        self.send_raw("TX.SEND_MESSAGE", text)
        net = self.db.active_net()
        self.db.insert("js8", {"net_id": net["id"] if net else None, "ts": now(), "kind": "TX",
                               "from_call": self.db.get("mycall"), "to_call": text.split(" ")[0],
                               "text": text, "snr": None, "grid": None, "freq": None})
        bus.publish("js8", {"kind": "TX", "text": text})

    def _session(self):
        host = self.db.get("js8_host") or "127.0.0.1"
        port = int(self.db.get("js8_port") or 2442)
        self.set_status("connecting")
        s = socket.create_connection((host, port), timeout=5)
        s.settimeout(None)
        with self.lock:
            self.sock = s
        self.set_status("connected")
        for t in ("STATION.GET_CALLSIGN", "STATION.GET_GRID", "RIG.GET_FREQ"):
            self.send_raw(t)
        buf = b""
        while not self.restart_flag:
            d = s.recv(65536)
            if not d:
                raise ConnectionError("JS8Call closed the connection")
            buf += d
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    self.handle(json.loads(line))
                except ValueError:
                    pass

    def handle(self, m):
        typ = m.get("type", "")
        p = m.get("params", {}) or {}
        val = m.get("value", "")
        if typ == "STATION.CALLSIGN":
            self.info["callsign"] = val
        elif typ == "STATION.GRID":
            self.info["grid"] = val
        elif typ == "RIG.FREQ":
            self.info["dial"] = p.get("DIAL")
            self.info["offset"] = p.get("OFFSET")
            self.info["freq_ts"] = time.time()
        if typ.startswith("STATION.") or typ.startswith("RIG."):
            bus.publish("js8_status", {"status": self.status, "info": self.info})
            return
        if typ in ("RX.DIRECTED", "RX.SPOT", "RX.ACTIVITY"):
            frm = p.get("FROM") or p.get("CALL") or ""
            grid = (p.get("GRID") or "").strip()
            if grid and frm:
                ll = maidenhead_to_latlon(grid)
                if ll and self._tracked(frm) and len(grid) >= 6:
                    record_position(self.db, frm.upper(), ll[0], ll[1], "JS8 grid " + grid)
            if typ == "RX.SPOT":
                return
            if typ == "RX.ACTIVITY" and not val.strip():
                return
            net = self.db.active_net()
            row = {"net_id": net["id"] if net else None, "ts": now(),
                   "kind": "DIRECTED" if typ == "RX.DIRECTED" else "ACTIVITY",
                   "from_call": frm, "to_call": p.get("TO", ""), "text": val,
                   "snr": p.get("SNR"), "grid": grid, "freq": p.get("FREQ") or p.get("DIAL")}
            if typ == "RX.DIRECTED":
                self.db.insert("js8", row)
                if net:
                    self.db.log(net["id"], "js8", "JS8 %s: %s" % (frm, val), base_call(frm))
            bus.publish("js8", row)

    def _tracked(self, call):
        net = self.db.active_net()
        if not net:
            return False
        r = self.db.one("SELECT 1 FROM checkins WHERE net_id=? AND upper(callsign) LIKE ?",
                        (net["id"], base_call(call) + "%"))
        return bool(r)
