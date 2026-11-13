"""SQLite storage for ARES Console."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS nets (
  id INTEGER PRIMARY KEY, name TEXT, ncs TEXT, frequency TEXT, notes TEXT,
  opened_at TEXT, closed_at TEXT);
CREATE TABLE IF NOT EXISTS checkins (
  id INTEGER PRIMARY KEY, net_id INTEGER, callsign TEXT, name TEXT, tactical TEXT,
  status TEXT DEFAULT 'Present', location TEXT DEFAULT '', notes TEXT DEFAULT '',
  time_in TEXT, time_out TEXT, updated_at TEXT, track INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY, net_id INTEGER, ts TEXT, kind TEXT, callsign TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS stations (
  callsign TEXT PRIMARY KEY, lat REAL, lon REAL, ts TEXT, source TEXT,
  symbol TEXT, comment TEXT, course INTEGER, speed INTEGER, raw TEXT);
CREATE TABLE IF NOT EXISTS track (
  id INTEGER PRIMARY KEY, callsign TEXT, lat REAL, lon REAL, ts TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS markers (
  id INTEGER PRIMARY KEY, net_id INTEGER, label TEXT, kind TEXT, lat REAL, lon REAL,
  notes TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS forms (
  id INTEGER PRIMARY KEY, net_id INTEGER, form_type TEXT, number TEXT, title TEXT,
  data TEXT, direction TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, mid TEXT, net_id INTEGER, box TEXT, from_addr TEXT,
  to_addrs TEXT, cc_addrs TEXT, subject TEXT, date TEXT, body TEXT, raw BLOB,
  size INTEGER, created_at TEXT, via TEXT, status TEXT, form_id INTEGER);
CREATE TABLE IF NOT EXISTS pending (
  mid TEXT PRIMARY KEY, from_addr TEXT, subject TEXT, size INTEGER, gateway TEXT, seen_at TEXT);
CREATE TABLE IF NOT EXISTS nodes (
  id INTEGER PRIMARY KEY, callsign TEXT, frequency TEXT, mode TEXT, bandwidth TEXT,
  grid TEXT, location TEXT, hours TEXT, notes TEXT, source TEXT, favorite INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS js8 (
  id INTEGER PRIMARY KEY, net_id INTEGER, ts TEXT, kind TEXT, from_call TEXT, to_call TEXT,
  text TEXT, snr INTEGER, grid TEXT, freq INTEGER);
"""

DEFAULT_SETTINGS = {
    "org_title": "Cass County ARES",
    "org_subtitle": "Net Control Station Console",
    "mycall": "",
    "operator_name": "",
    "grid": "",
    "home_lat": "39.0",
    "home_lon": "-98.0",
    "aprs_enabled": "1",
    "aprs_server": "rotate.aprs2.net",
    "aprs_port": "14580",
    "aprs_passcode": "-1",
    "aprs_extra_filter": "",
    "rig_enabled": "0",
    "rig_host": "127.0.0.1",
    "rig_port": "4532",
    "rig_command": "",
    "ardop_host": "127.0.0.1",
    "ardop_port": "8515",
    "ardop_bw": "2000MAX",
    "ardop_ptt_via_rig": "1",
    "ardop_command": "ardopcf {port}" if os.name == "nt" else "ardopcf {port} pulse pulse",
    "winlink_password": "",
    "winlink_select_timeout": "120",
    "js8_enabled": "0",
    "js8_host": "127.0.0.1",
    "js8_port": "2442",
    "js8_command": "js8call",
    "wl_forms_dir": "",
    "map_source": "usgs_topo",
    "map_tiles": "",
    "statuses": "Present,Away,Checked Out",
}

SECRET_KEYS = {"winlink_password"}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def q(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            rows = [dict(r) for r in cur.fetchall()]
            return rows

    def one(self, sql, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    def insert(self, table, data):
        keys = list(data)
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (table, ",".join(keys), ",".join("?" * len(keys)))
        return self.x(sql, [data[k] for k in keys])

    def update(self, table, id_, data, key="id"):
        if not data:
            return
        sets = ",".join("%s=?" % k for k in data)
        self.x("UPDATE %s SET %s WHERE %s=?" % (table, sets, key), list(data.values()) + [id_])

    # ---- settings
    def settings(self, include_secret=False):
        s = dict(DEFAULT_SETTINGS)
        for r in self.q("SELECT key, value FROM settings"):
            s[r["key"]] = r["value"]
        if not include_secret:
            for k in SECRET_KEYS:
                s[k] = "********" if s.get(k) else ""
        return s

    def get(self, key):
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r["value"] if r else DEFAULT_SETTINGS.get(key, "")

    def set_settings(self, data):
        for k, v in data.items():
            if k in SECRET_KEYS and v == "********":
                continue
            self.x("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(v)))

    # ---- nets
    def active_net(self):
        return self.one("SELECT * FROM nets WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1")

    def log(self, net_id, kind, text, callsign=""):
        return self.insert("activity", {"net_id": net_id, "ts": now(), "kind": kind,
                                         "callsign": callsign, "text": text})


def jdump(o):
    return json.dumps(o, default=str)
