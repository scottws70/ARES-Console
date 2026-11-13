"""HTTP server + JSON API for ARES Console (Python standard library only)."""
import email.parser
import email.policy
import json
import mimetypes
import os
import queue
import re
import shlex
import shutil
import subprocess
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import forms as formdefs
from . import mcforms, report, wlforms, b2f
from .aprs import APRSIS, base_call, parse_location, record_position
from .db import DB, now, jdump
from .events import bus
from .js8 import JS8
from .rig import Rig
from .tiles import TileCache, count_tiles
from .winlink import Winlink, import_pat_rmslist, default_forms_dir

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")


class App:
    def __init__(self, data_dir, host, port):
        self.data_dir = data_dir
        self.host, self.port = host, port
        self.db = DB(os.path.join(data_dir, "ares.db"))
        self.rig = Rig(self.db)
        self.aprs = APRSIS(self.db)
        self.js8 = JS8(self.db)
        self.wl = Winlink(self.db, self.rig)
        self.mcf_cache = None
        self.tiles = TileCache(self.db, data_dir)
        self.aprs.start()
        self.js8.start()

    # helpers ---------------------------------------------------------
    def net_or_none(self):
        return self.db.active_net()

    def ctx(self):
        s = self.db.settings()
        return {"mycall": (s["mycall"] or "N0CALL").upper(), "grid": s["grid"],
                "lat": s["home_lat"], "lon": s["home_lon"],
                "host": "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host, "port": self.port}

    def forms_dir(self):
        return default_forms_dir(self.db, self.data_dir)

    def mcforms(self):
        if self.mcf_cache is None:
            self.mcf_cache = mcforms.load_all(self.data_dir)
        return self.mcf_cache

    def checkin_position(self, c):
        """Plot a manually-entered location (grid or lat,lon) for a station without APRS."""
        ll = parse_location(c.get("location") or "")
        if ll and c.get("callsign"):
            record_position(self.db, c["callsign"].upper(), ll[0], ll[1], "manual: " + c["location"])


class Handler(BaseHTTPRequestHandler):
    server_version = "ARESConsole/1.0"
    app: App = None
    routes = []

    def log_message(self, fmt, *args):
        pass

    # plumbing --------------------------------------------------------
    def send_json(self, obj, code=200):
        data = jdump(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, text, ctype="text/html; charset=utf-8", code=200, extra=None):
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def body_bytes(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def body(self):
        b = self.body_bytes()
        return json.loads(b) if b else {}

    def query(self):
        return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))

    def dispatch(self, method):
        path = urllib.parse.urlparse(self.path).path
        for m, rx, fn in self.routes:
            if m != method:
                continue
            mt = rx.fullmatch(path)
            if mt:
                try:
                    return fn(self, *mt.groups())
                except (ValueError, KeyError, RuntimeError, FileNotFoundError) as e:
                    return self.send_json({"error": str(e)}, 400)
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as e:  # noqa
                    traceback.print_exc()
                    return self.send_json({"error": "%s: %s" % (type(e).__name__, e)}, 500)
        if method == "GET":
            return self.static(path)
        self.send_json({"error": "not found"}, 404)

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_PUT(self):
        self.dispatch("PUT")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def static(self, path):
        if path == "/":
            path = "/index.html"
        p = os.path.realpath(os.path.join(STATIC, path.lstrip("/")))
        if not p.startswith(os.path.realpath(STATIC)) or not os.path.isfile(p):
            return self.send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        with open(p, "rb") as fh:
            self.send_text(fh.read(), ctype, extra={"Cache-Control": "no-cache"})


def route(method, pattern):
    def deco(fn):
        Handler.routes.append((method, re.compile(pattern), fn))
        return fn
    return deco


def A(h):
    return h.app


# ------------------------------------------------------------------ events (SSE)
@route("GET", r"/api/events")
def events(h):
    q = bus.subscribe()
    h.send_response(200)
    h.send_header("Content-Type", "text/event-stream")
    h.send_header("Cache-Control", "no-cache")
    h.end_headers()
    try:
        h.wfile.write(b": hello\n\n")
        h.wfile.flush()
        while True:
            try:
                msg = q.get(timeout=20)
                h.wfile.write(("data: %s\n\n" % jdump(msg)).encode())
            except queue.Empty:
                h.wfile.write(b": ping\n\n")
            h.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        bus.unsubscribe(q)


# ------------------------------------------------------------------ app
@route("GET", r"/api/version")
def version(h):
    from . import __version__
    return h.send_json({"app": "ARES Console", "version": __version__, "data_dir": A(h).data_dir})


@route("POST", r"/api/shutdown")
def shutdown(h):
    """Stop the ARES Console server (used by the Quit button)."""
    a = A(h)
    net = a.net_or_none()
    if net:
        a.db.log(net["id"], "net", "ARES Console shut down by operator (net still open)")
    h.send_json({"ok": True})
    threading.Thread(target=Handler.httpd.shutdown, daemon=True).start()


# ------------------------------------------------------------------ settings / state
@route("GET", r"/api/state")
def state(h):
    a = A(h)
    net = a.net_or_none()
    return h.send_json({
        "settings": a.db.settings(), "net": net,
        "checkins": a.db.q("SELECT * FROM checkins WHERE net_id=? ORDER BY id", (net["id"],)) if net else [],
        "aprs": {"status": a.aprs.status, "packets": a.aprs.packets, "filter": a.aprs.current_filter},
        "js8": {"status": a.js8.status, "info": a.js8.info},
        "winlink": a.wl.status(),
    })


@route("GET", r"/api/settings")
def get_settings(h):
    return h.send_json(A(h).db.settings())


@route("POST", r"/api/settings")
def set_settings(h):
    a = A(h)
    data = h.body()
    a.db.set_settings(data)
    if any(k.startswith("aprs_") or k == "mycall" for k in data):
        a.aprs.restart()
    if any(k.startswith("js8_") for k in data):
        a.js8.restart()
    bus.publish("settings", a.db.settings())
    return h.send_json(a.db.settings())


# ------------------------------------------------------------------ nets
@route("POST", r"/api/net/open")
def net_open(h):
    a = A(h)
    if a.net_or_none():
        raise ValueError("A net is already open. Close it first.")
    d = h.body()
    nid = a.db.insert("nets", {"name": d.get("name") or "ARES Net", "ncs": d.get("ncs") or a.db.get("mycall"),
                               "frequency": d.get("frequency", ""), "notes": d.get("notes", ""),
                               "opened_at": now(), "closed_at": None})
    a.db.log(nid, "net", "Net opened: %s by %s on %s" % (d.get("name") or "ARES Net", d.get("ncs") or a.db.get("mycall"),
                                                          d.get("frequency", "")))
    if d.get("carry_over"):
        prev = a.db.one("SELECT id FROM nets WHERE id<? ORDER BY id DESC LIMIT 1", (nid,))
        if prev:
            for c in a.db.q("SELECT * FROM checkins WHERE net_id=? AND status!='Checked Out'", (prev["id"],)):
                a.db.insert("checkins", {"net_id": nid, "callsign": c["callsign"], "name": c["name"],
                                         "tactical": c["tactical"], "status": c["status"], "location": c["location"],
                                         "notes": c["notes"], "time_in": now(), "updated_at": now(), "track": c["track"]})
    a.aprs.refresh_filter()
    bus.publish("net", {})
    return h.send_json(a.db.one("SELECT * FROM nets WHERE id=?", (nid,)))


@route("PUT", r"/api/net/(\d+)")
def net_update(h, nid):
    a = A(h)
    d = h.body()
    a.db.update("nets", int(nid), {k: d[k] for k in ("name", "ncs", "frequency", "notes") if k in d})
    bus.publish("net", {})
    return h.send_json({"ok": True})


@route("POST", r"/api/net/close")
def net_close(h):
    a = A(h)
    net = a.net_or_none()
    if not net:
        raise ValueError("No open net")
    d = h.body()
    if d.get("checkout_all", True):
        a.db.x("UPDATE checkins SET status='Checked Out', time_out=COALESCE(time_out, ?) "
               "WHERE net_id=? AND status!='Checked Out'", (now(), net["id"]))
    a.db.log(net["id"], "net", "Net closed")
    a.db.update("nets", net["id"], {"closed_at": now()})
    a.aprs.refresh_filter()
    bus.publish("net", {})
    return h.send_json({"ok": True, "net_id": net["id"]})


@route("GET", r"/api/nets")
def nets(h):
    return h.send_json(A(h).db.q(
        "SELECT n.*, (SELECT count(*) FROM checkins c WHERE c.net_id=n.id) AS checkins FROM nets n ORDER BY id DESC"))


# ------------------------------------------------------------------ check-ins
CHECKIN_FIELDS = ("callsign", "name", "tactical", "status", "location", "notes", "track")


@route("POST", r"/api/checkins")
def checkin_add(h):
    a = A(h)
    net = a.net_or_none()
    if not net:
        raise ValueError("Open a net first")
    d = h.body()
    call = (d.get("callsign") or "").strip().upper()
    if not call:
        raise ValueError("Callsign required")
    existing = a.db.one("SELECT * FROM checkins WHERE net_id=? AND upper(callsign)=?", (net["id"], call))
    if existing:
        upd = {"status": d.get("status") or "Present", "updated_at": now(), "time_out": None}
        a.db.update("checkins", existing["id"], upd)
        a.db.log(net["id"], "checkin", "%s re-checked in (%s)" % (call, upd["status"]), call)
        cid = existing["id"]
    else:
        row = {"net_id": net["id"], "callsign": call, "name": d.get("name", ""), "tactical": d.get("tactical", ""),
               "status": d.get("status") or "Present", "location": d.get("location", ""),
               "notes": d.get("notes", ""), "time_in": now(), "updated_at": now(),
               "track": 1 if d.get("track", True) else 0}
        cid = a.db.insert("checkins", row)
        a.db.log(net["id"], "checkin", "%s checked in%s%s" % (
            call, (" - " + row["name"]) if row["name"] else "",
            (" @ " + row["location"]) if row["location"] else ""), call)
        a.checkin_position(row)
    a.aprs.refresh_filter()
    bus.publish("checkins", {})
    return h.send_json(a.db.one("SELECT * FROM checkins WHERE id=?", (cid,)))


@route("PUT", r"/api/checkins/(\d+)")
def checkin_update(h, cid):
    a = A(h)
    cid = int(cid)
    old = a.db.one("SELECT * FROM checkins WHERE id=?", (cid,))
    if not old:
        raise KeyError("no such check-in")
    d = h.body()
    upd = {k: d[k] for k in CHECKIN_FIELDS if k in d}
    if "callsign" in upd:
        upd["callsign"] = upd["callsign"].strip().upper()
    if "track" in upd:
        upd["track"] = 1 if upd["track"] else 0
    upd["updated_at"] = now()
    if upd.get("status") == "Checked Out" and old["status"] != "Checked Out":
        upd["time_out"] = now()
    elif "status" in upd and upd["status"] != "Checked Out":
        upd["time_out"] = None
    a.db.update("checkins", cid, upd)
    call = upd.get("callsign", old["callsign"])
    for k in ("status", "location", "notes", "name", "tactical", "callsign"):
        if k in upd and (upd[k] or "") != (old[k] or ""):
            if k == "status":
                a.db.log(old["net_id"], "status", "%s status: %s -> %s" % (call, old[k], upd[k]), call)
            else:
                a.db.log(old["net_id"], "update", "%s %s: %s" % (call, k, upd[k]), call)
    if "location" in upd and upd["location"] != old["location"]:
        a.checkin_position({"callsign": call, "location": upd["location"]})
    a.aprs.refresh_filter()
    bus.publish("checkins", {})
    return h.send_json(a.db.one("SELECT * FROM checkins WHERE id=?", (cid,)))


@route("DELETE", r"/api/checkins/(\d+)")
def checkin_delete(h, cid):
    a = A(h)
    old = a.db.one("SELECT * FROM checkins WHERE id=?", (int(cid),))
    if old:
        a.db.x("DELETE FROM checkins WHERE id=?", (int(cid),))
        a.db.log(old["net_id"], "update", "%s removed from roster" % old["callsign"], old["callsign"])
    a.aprs.refresh_filter()
    bus.publish("checkins", {})
    return h.send_json({"ok": True})


# ------------------------------------------------------------------ activity log
@route("GET", r"/api/activity")
def activity(h):
    a = A(h)
    q = h.query()
    nid = q.get("net_id") or (a.net_or_none() or {}).get("id")
    if not nid:
        return h.send_json([])
    return h.send_json(a.db.q("SELECT * FROM activity WHERE net_id=? ORDER BY ts DESC, id DESC LIMIT 2000", (nid,)))


@route("POST", r"/api/activity")
def activity_add(h):
    a = A(h)
    net = a.net_or_none()
    if not net:
        raise ValueError("Open a net first")
    d = h.body()
    a.db.log(net["id"], d.get("kind") or "note", d.get("text", ""), (d.get("callsign") or "").upper())
    bus.publish("activity", {})
    return h.send_json({"ok": True})


# ------------------------------------------------------------------ map
@route("GET", r"/api/map")
def map_data(h):
    a = A(h)
    net = a.net_or_none()
    checkins = a.db.q("SELECT * FROM checkins WHERE net_id=?", (net["id"],)) if net else []
    bases = {base_call(c["callsign"]): c for c in checkins}
    stations = []
    for s in a.db.q("SELECT * FROM stations ORDER BY ts DESC"):
        c = bases.get(base_call(s["callsign"]))
        if c is None and not h.query().get("all"):
            continue
        s["checkin"] = c
        s["track"] = a.db.q("SELECT lat, lon, ts FROM track WHERE callsign=? ORDER BY id DESC LIMIT 30", (s["callsign"],))
        stations.append(s)
    markers = a.db.q("SELECT * FROM markers WHERE net_id IS NULL OR net_id=?", (net["id"] if net else -1,))
    return h.send_json({"stations": stations, "markers": markers})


@route("POST", r"/api/markers")
def marker_add(h):
    a = A(h)
    d = h.body()
    net = a.net_or_none()
    mid = a.db.insert("markers", {"net_id": net["id"] if (net and not d.get("permanent")) else None,
                                  "label": d.get("label") or "Spot", "kind": d.get("kind") or "spot",
                                  "lat": float(d["lat"]), "lon": float(d["lon"]), "notes": d.get("notes", ""),
                                  "created_at": now()})
    if net:
        a.db.log(net["id"], "map", "Map location added: %s (%.5f, %.5f)" % (d.get("label"), float(d["lat"]), float(d["lon"])))
    bus.publish("markers", {})
    return h.send_json(a.db.one("SELECT * FROM markers WHERE id=?", (mid,)))


@route("PUT", r"/api/markers/(\d+)")
def marker_update(h, mid):
    a = A(h)
    d = h.body()
    a.db.update("markers", int(mid), {k: d[k] for k in ("label", "kind", "lat", "lon", "notes") if k in d})
    bus.publish("markers", {})
    return h.send_json({"ok": True})


@route("DELETE", r"/api/markers/(\d+)")
def marker_delete(h, mid):
    a = A(h)
    m = a.db.one("SELECT * FROM markers WHERE id=?", (int(mid),))
    a.db.x("DELETE FROM markers WHERE id=?", (int(mid),))
    net = a.net_or_none()
    if net and m:
        a.db.log(net["id"], "map", "Map location removed: %s" % m["label"])
    bus.publish("markers", {})
    return h.send_json({"ok": True})


# ------------------------------------------------------------------ offline map tiles
_BLANK_HEADERS = {"Cache-Control": "no-store"}


@route("GET", r"/tiles/(\d+)/(\d+)/(\d+)\.png")
def tile(h, z, x, y):
    data, src = A(h).tiles.get(int(z), int(x), int(y))
    if data is None:
        return h.send_text(b"", "image/png", code=404, extra=_BLANK_HEADERS)
    ctype = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
    return h.send_text(data, ctype, extra={"Cache-Control": "max-age=3600", "X-Tile-Source": src})


@route("GET", r"/api/tiles")
def tiles_status(h):
    return h.send_json(A(h).tiles.status())


def _bounds(d):
    return (float(d["south"]), float(d["west"]), float(d["north"]), float(d["east"]))


@route("POST", r"/api/tiles/estimate")
def tiles_estimate(h):
    d = h.body()
    return h.send_json({"tiles": count_tiles(_bounds(d), int(d["zmin"]), int(d["zmax"]))})


@route("POST", r"/api/tiles/seed")
def tiles_seed(h):
    d = h.body()
    n = A(h).tiles.start_seed(_bounds(d), d["zmin"], d["zmax"])
    return h.send_json({"ok": True, "tiles": n})


@route("POST", r"/api/tiles/cancel")
def tiles_cancel(h):
    A(h).tiles.cancel_seed()
    return h.send_json({"ok": True})


@route("POST", r"/api/tiles/retry")
def tiles_retry(h):
    A(h).tiles.offline_until = 0
    return h.send_json({"ok": True})


@route("DELETE", r"/api/tiles")
def tiles_clear(h):
    A(h).tiles.clear()
    return h.send_json({"ok": True})


# ------------------------------------------------------------------ forms
@route("GET", r"/api/formdefs")
def formdefs_get(h):
    a = A(h)
    return h.send_json({"builtin": formdefs.FORMS, "mcforms": a.mcforms(), "wl_dir": a.forms_dir()})


@route("GET", r"/api/forms")
def forms_list(h):
    a = A(h)
    q = h.query()
    if q.get("net_id") == "all":
        rows = a.db.q("SELECT id, net_id, form_type, number, title, direction, created_at, updated_at FROM forms ORDER BY id DESC")
    else:
        net = a.net_or_none()
        nid = q.get("net_id") or (net["id"] if net else None)
        rows = a.db.q("SELECT id, net_id, form_type, number, title, direction, created_at, updated_at FROM forms "
                      "WHERE net_id IS ? ORDER BY id DESC", (int(nid) if nid else None,))
    for r in rows:
        r["form_name"] = report.form_name(r["form_type"])
    return h.send_json(rows)


def _form_title(ft, data):
    if ft in formdefs.FORMS:
        return formdefs.title_for(ft, data)
    if ft.startswith("WL:"):
        return data.get("subject") or ft
    if ft.startswith("MCF:"):
        return data.get("title") or ft
    return ft


def _next_number(a, ft):
    r = a.db.one("SELECT count(*) AS n FROM forms WHERE form_type=?", (ft,))
    return str((r["n"] if r else 0) + 1)


@route("POST", r"/api/forms")
def forms_create(h):
    a = A(h)
    d = h.body()
    ft = d["form_type"]
    data = d.get("data") or {}
    if ft == "RADIOGRAM" and not data.get("check"):
        data["check"] = formdefs.radiogram_check(data.get("text"))
    if ft.startswith("MCF:"):
        frm = a.mcforms().get(ft[4:])
        if frm:
            data["compact"], data["readable"] = mcforms.encode(frm, data.get("answers", {}))
            data["title"] = frm["title"]
    net = a.net_or_none()
    fid = a.db.insert("forms", {"net_id": net["id"] if net else None, "form_type": ft,
                                "number": data.get("msg_no") or data.get("number") or _next_number(a, ft),
                                "title": _form_title(ft, data), "data": json.dumps(data),
                                "direction": data.get("direction", ""), "created_at": now(), "updated_at": now()})
    if net:
        a.db.log(net["id"], "form", "%s created: %s" % (report.form_name(ft), _form_title(ft, data)))
    bus.publish("forms", {})
    return h.send_json(_form_get(a, fid))


def _form_get(a, fid):
    r = a.db.one("SELECT * FROM forms WHERE id=?", (int(fid),))
    if not r:
        raise KeyError("no such form")
    r["data"] = json.loads(r["data"] or "{}")
    r["form_name"] = report.form_name(r["form_type"])
    return r


@route("GET", r"/api/forms/(\d+)")
def forms_get(h, fid):
    return h.send_json(_form_get(A(h), fid))


@route("PUT", r"/api/forms/(\d+)")
def forms_update(h, fid):
    a = A(h)
    d = h.body()
    old = _form_get(a, fid)
    ft = old["form_type"]
    data = d.get("data") or {}
    if ft == "RADIOGRAM" and not data.get("check"):
        data["check"] = formdefs.radiogram_check(data.get("text"))
    if ft.startswith("MCF:"):
        frm = a.mcforms().get(ft[4:])
        if frm:
            data["compact"], data["readable"] = mcforms.encode(frm, data.get("answers", {}))
            data["title"] = frm["title"]
    a.db.update("forms", int(fid), {"data": json.dumps(data), "title": _form_title(ft, data),
                                    "direction": data.get("direction", ""), "updated_at": now(),
                                    "number": data.get("msg_no") or data.get("number") or old["number"]})
    bus.publish("forms", {})
    return h.send_json(_form_get(a, fid))


@route("DELETE", r"/api/forms/(\d+)")
def forms_delete(h, fid):
    a = A(h)
    f = _form_get(a, fid)
    a.db.x("DELETE FROM forms WHERE id=?", (int(fid),))
    if f["net_id"]:
        a.db.log(f["net_id"], "form", "%s deleted: %s" % (f["form_name"], f["title"]))
    bus.publish("forms", {})
    return h.send_json({"ok": True})


@route("GET", r"/api/forms/(\d+)/text")
def forms_text(h, fid):
    a = A(h)
    f = _form_get(a, fid)
    f["data"] = json.dumps(f["data"])
    txt = report.form_text(f, a.db.settings())
    return h.send_json({"text": txt, "subject": _form_subject(f)})


def _form_subject(f):
    data = json.loads(f["data"]) if isinstance(f["data"], str) else f["data"]
    ft = f["form_type"]
    if ft in formdefs.FORMS:
        return formdefs.subject_for(ft, data)
    if ft.startswith("WL:"):
        return data.get("subject", "")
    return data.get("title", ft)


@route("GET", r"/api/forms/(\d+)/print")
def forms_print(h, fid):
    a = A(h)
    f = _form_get(a, fid)
    s = a.db.settings()
    f2 = dict(f, data=json.dumps(f["data"]))
    import html as _h
    page = ("<!doctype html><meta charset=utf-8><title>%s</title><style>body{font-family:monospace;margin:24px}"
            "pre{white-space:pre-wrap;font-size:13px}@media print{button{display:none}}</style>"
            "<button onclick=print()>Print</button><h3 style='font-family:sans-serif'>%s</h3><pre>%s</pre>") % (
        _h.escape(f["form_name"]), _h.escape(s["org_title"]), _h.escape(report.form_text(f2, s)))
    return h.send_text(page)


@route("POST", r"/api/forms/(\d+)/send")
def forms_send(h, fid):
    """Send a form via Winlink (queue in outbox) or JS8Call."""
    a = A(h)
    d = h.body()
    f = _form_get(a, fid)
    f2 = dict(f, data=json.dumps(f["data"]))
    via = d.get("via", "winlink")
    net = a.net_or_none()
    if via == "js8":
        text = d.get("text") or f["data"].get("compact") or report.form_text(f2, a.db.settings())
        dest = (d.get("to") or "").strip()
        a.js8.send_message(("%s MSG %s" % (dest, text)).strip() if dest else text)
        if net:
            a.db.log(net["id"], "js8", "Form sent via JS8Call to %s: %s" % (dest, f["title"]))
        return h.send_json({"ok": True})
    attachments = []
    if f["form_type"].startswith("WL:") and f["data"].get("xml"):
        attachments.append((f["data"]["xml_name"], f["data"]["xml"].encode("utf-8")))
    body = d.get("body") or report.form_text(f2, a.db.settings())
    if f["form_type"].startswith("WL:") and not d.get("body"):
        body = f["data"].get("body", "")
    mid = a.wl.compose(d.get("to", ""), d.get("cc", ""), d.get("subject") or _form_subject(f), body,
                       net_id=net["id"] if net else None, form_id=f["id"], attachments=attachments)
    return h.send_json({"ok": True, "message_id": mid})


@route("POST", r"/api/mcforms/download")
def mcforms_download(h):
    a = A(h)
    res = mcforms.download(a.data_dir)
    a.mcf_cache = None
    return h.send_json(dict(res, forms=len(a.mcforms())))


# ------------------------------------------------------------------ Winlink standard forms
@route("GET", r"/api/wlforms")
def wlforms_list(h):
    a = A(h)
    return h.send_json({"dir": a.forms_dir(), "templates": wlforms.list_templates(a.forms_dir())})


@route("GET", r"/wlforms/open")
def wlforms_open(h):
    a = A(h)
    rel = h.query().get("tpl", "")
    ctx = a.ctx()
    ctx["host"] = (h.headers.get("Host") or "").split(":")[0] or ctx["host"]
    return h.send_text(wlforms.initial_html(a.forms_dir(), rel, ctx))


@route("POST", r"/wlforms/submit")
def wlforms_submit(h):
    a = A(h)
    rel = h.query().get("tpl", "")
    ctype = h.headers.get("Content-Type", "")
    raw = h.body_bytes()
    fields = {}
    if "multipart/form-data" in ctype:
        msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw)
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                fields[name] = payload.decode("utf-8", "replace")
    else:
        fields = dict(urllib.parse.parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=True))
    res = wlforms.submit(a.forms_dir(), rel, fields, a.ctx())
    res["fields"] = fields
    net = a.net_or_none()
    ft = "WL:" + rel
    fid = a.db.insert("forms", {"net_id": net["id"] if net else None, "form_type": ft,
                                "number": _next_number(a, ft), "title": res["subject"] or rel,
                                "data": json.dumps(res), "direction": "Outgoing", "created_at": now(),
                                "updated_at": now()})
    if net:
        a.db.log(net["id"], "form", "Winlink form completed: %s" % (res["subject"] or rel))
    bus.publish("forms", {"wlform": fid})
    page = """<!doctype html><meta charset=utf-8><title>Form saved</title>
<body style="font-family:sans-serif;padding:30px"><h2>Form saved to ARES Console</h2>
<p>Subject: <b>%s</b></p><p>Return to the ARES Console window to address and send it via Winlink.</p>
<button onclick="window.close()">Close this window</button>
<script>try{window.opener&&window.opener.postMessage({type:'wlform',id:%d},'*')}catch(e){};
try{new BroadcastChannel('ares').postMessage({type:'wlform',id:%d})}catch(e){}</script>""" % (
        (res["subject"] or "").replace("<", "&lt;"), fid, fid)
    return h.send_text(page)


@route("GET", r"/wlforms/view/(\d+)")
def wlforms_view(h, msg_id):
    a = A(h)
    m = a.db.one("SELECT raw FROM messages WHERE id=?", (int(msg_id),))
    if not m:
        raise KeyError("no message")
    pm = b2f.parse_message(bytes(m["raw"]))
    for fobj in pm["files"]:
        if fobj["name"].lower().startswith("rms_express_form") and fobj["name"].lower().endswith(".xml"):
            return h.send_text(wlforms.render_viewer(a.forms_dir(), fobj["data"], a.ctx()))
    return h.send_text("<p>No Winlink form attachment in this message.</p>")


# ------------------------------------------------------------------ messages / winlink
@route("GET", r"/api/messages")
def messages(h):
    a = A(h)
    box = h.query().get("box", "inbox")
    rows = a.db.q("SELECT id, mid, box, from_addr, to_addrs, cc_addrs, subject, date, size, status, via, form_id "
                  "FROM messages WHERE box=? ORDER BY id DESC", (box,))
    counts = {r["box"]: r["n"] for r in a.db.q("SELECT box, count(*) AS n FROM messages GROUP BY box")}
    counts["pending"] = a.db.one("SELECT count(*) AS n FROM pending")["n"]
    return h.send_json({"messages": rows, "counts": counts})


@route("GET", r"/api/messages/(\d+)")
def message_get(h, mid):
    a = A(h)
    m = a.db.one("SELECT * FROM messages WHERE id=?", (int(mid),))
    if not m:
        raise KeyError("no such message")
    raw = bytes(m.pop("raw") or b"")
    pm = b2f.parse_message(raw) if raw else {"files": [], "headers": []}
    m["files"] = [{"name": f["name"], "size": len(f["data"])} for f in pm["files"]]
    m["has_form"] = any(f["name"].lower().startswith("rms_express_form") for f in pm["files"])
    m["headers"] = pm.get("headers", [])
    if m["box"] == "inbox" and m["status"] == "unread":
        a.db.x("UPDATE messages SET status='read' WHERE id=?", (int(mid),))
    return h.send_json(m)


@route("GET", r"/api/messages/(\d+)/file/(\d+)")
def message_file(h, mid, idx):
    a = A(h)
    m = a.db.one("SELECT raw FROM messages WHERE id=?", (int(mid),))
    pm = b2f.parse_message(bytes(m["raw"]))
    f = pm["files"][int(idx)]
    ctype = mimetypes.guess_type(f["name"])[0] or "application/octet-stream"
    return h.send_text(f["data"], ctype, extra={
        "Content-Disposition": 'attachment; filename="%s"' % f["name"].replace('"', "")})


@route("POST", r"/api/messages")
def message_compose(h):
    a = A(h)
    d = h.body()
    net = a.net_or_none()
    mid = a.wl.compose(d.get("to"), d.get("cc"), d.get("subject"), d.get("body"),
                       net_id=net["id"] if net else None)
    return h.send_json({"ok": True, "id": mid})


@route("DELETE", r"/api/messages/(\d+)")
def message_delete(h, mid):
    a = A(h)
    a.db.x("DELETE FROM messages WHERE id=?", (int(mid),))
    bus.publish("messages", {})
    return h.send_json({"ok": True})


@route("GET", r"/api/winlink/pending")
def wl_pending(h):
    return h.send_json(A(h).db.q("SELECT * FROM pending ORDER BY seen_at DESC"))


@route("DELETE", r"/api/winlink/pending")
def wl_pending_clear(h):
    A(h).db.x("DELETE FROM pending")
    bus.publish("messages", {})
    return h.send_json({"ok": True})


@route("GET", r"/api/winlink/status")
def wl_status(h):
    a = A(h)
    return h.send_json(dict(a.wl.status(), log=a.wl.log_lines[-200:]))


@route("POST", r"/api/winlink/connect")
def wl_connect(h):
    a = A(h)
    d = h.body()
    a.wl.start(d.get("transport", "ardop"), d.get("gateway", ""), d.get("freq"),
               mode=d.get("mode", "interactive"), preselect=d.get("mids"),
               host=d.get("host"), port=d.get("port"))
    return h.send_json({"ok": True})


@route("POST", r"/api/winlink/abort")
def wl_abort(h):
    A(h).wl.abort()
    return h.send_json({"ok": True})


@route("POST", r"/api/winlink/select")
def wl_select(h):
    A(h).wl.choose(h.body().get("choices", {}))
    return h.send_json({"ok": True})


# ------------------------------------------------------------------ gateway nodes
@route("GET", r"/api/nodes")
def nodes(h):
    return h.send_json(A(h).db.q("SELECT * FROM nodes ORDER BY favorite DESC, CASE WHEN source='pat' THEN CAST(location AS INTEGER) ELSE 0 END, callsign, CAST(frequency AS REAL)"))


NODE_FIELDS = ("callsign", "frequency", "mode", "bandwidth", "grid", "location", "hours", "notes", "favorite")


@route("POST", r"/api/nodes")
def node_add(h):
    a = A(h)
    d = h.body()
    row = {k: d.get(k, "") for k in NODE_FIELDS}
    row["callsign"] = (row["callsign"] or "").upper()
    row["favorite"] = 1 if d.get("favorite") else 0
    row["source"] = "manual"
    nid = a.db.insert("nodes", row)
    return h.send_json(a.db.one("SELECT * FROM nodes WHERE id=?", (nid,)))


@route("PUT", r"/api/nodes/(\d+)")
def node_update(h, nid):
    a = A(h)
    d = h.body()
    upd = {k: d[k] for k in NODE_FIELDS if k in d}
    if "favorite" in upd:
        upd["favorite"] = 1 if upd["favorite"] else 0
    a.db.update("nodes", int(nid), upd)
    return h.send_json({"ok": True})


@route("DELETE", r"/api/nodes/(\d+)")
def node_delete(h, nid):
    A(h).db.x("DELETE FROM nodes WHERE id=?", (int(nid),))
    return h.send_json({"ok": True})


@route("POST", r"/api/nodes/import_pat")
def node_import(h):
    d = h.body()
    n = import_pat_rmslist(A(h).db, d.get("mode", "ardop"), bool(d.get("force")))
    return h.send_json({"imported": n})


# ------------------------------------------------------------------ JS8
@route("GET", r"/api/js8")
def js8_list(h):
    return h.send_json(A(h).db.q("SELECT * FROM js8 ORDER BY id DESC LIMIT 500"))


def _js8call_pids():
    """PIDs of running JS8Call processes (Linux /proc, else pgrep/tasklist)."""
    pids = []
    if os.path.isdir("/proc"):
        for d in os.listdir("/proc"):
            if d.isdigit():
                try:
                    with open("/proc/%s/comm" % d) as fh:
                        if fh.read().strip().lower().startswith("js8call"):
                            pids.append(int(d))
                except OSError:
                    pass
        return pids
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq js8call.exe", "/NH"], capture_output=True, text=True).stdout
            return [1] if "js8call" in out.lower() else []
        out = subprocess.run(["pgrep", "-i", "js8call"], capture_output=True, text=True).stdout
        return [int(x) for x in out.split()]
    except (OSError, ValueError):
        return []


@route("GET", r"/api/js8/app")
def js8_app(h):
    a = A(h)
    return h.send_json({"running": bool(_js8call_pids()), "connected": a.js8.connected(),
                        "enabled": a.db.get("js8_enabled") == "1", "command": a.db.get("js8_command")})


@route("POST", r"/api/js8/launch")
def js8_launch(h):
    """Start the JS8Call program on this computer (if it isn't already running)."""
    a = A(h)
    enabled_now = False
    if a.db.get("js8_enabled") != "1":
        a.db.set_settings({"js8_enabled": "1"})
        enabled_now = True
        bus.publish("settings", a.db.settings())
    if _js8call_pids():
        a.js8.restart()
        return h.send_json({"ok": True, "already_running": True, "enabled_now": enabled_now})
    cmd = shlex.split(a.db.get("js8_command") or "js8call")
    exe = shutil.which(cmd[0]) if cmd else None
    if not exe and os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("LOCALAPPDATA", "")):
            cand = os.path.join(base, "js8call", "bin", "js8call.exe")
            if os.path.isfile(cand):
                exe = cand
                break
    if not exe:
        raise ValueError("JS8Call program not found (%s). Install JS8Call or set its command in Settings."
                         % (cmd[0] if cmd else "js8call"))
    kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True  # keeps running if ARES Console is closed
    subprocess.Popen([exe] + cmd[1:], **kw)
    net = a.net_or_none()
    if net:
        a.db.log(net["id"], "radio", "JS8Call started")
    # JS8Call takes a few seconds to open its API port; nudge the client to connect promptly.
    for delay in (6, 12, 20):
        threading.Timer(delay, lambda: (not a.js8.connected()) and a.js8.restart()).start()
    return h.send_json({"ok": True, "already_running": False, "enabled_now": enabled_now})


@route("POST", r"/api/js8/send")
def js8_send(h):
    a = A(h)
    a.js8.send_message(h.body().get("text", ""))
    return h.send_json({"ok": True})


# ------------------------------------------------------------------ rig
@route("GET", r"/api/rig")
def rig_get(h):
    a = A(h)
    if a.db.get("rig_enabled") != "1":
        return h.send_json({"ok": False, "error": "rig control disabled"})
    return h.send_json(a.rig.status())


@route("POST", r"/api/rig")
def rig_set(h):
    a = A(h)
    d = h.body()
    if a.db.get("rig_enabled") != "1":
        if a.js8.connected() and d.get("freq"):
            a.js8.set_freq(dial_hz=float(d["freq"]))
            return h.send_json({"ok": True, "via": "JS8Call"})
        raise ValueError("Rig control is off: enable rigctld (or JS8Call) in Settings")
    if d.get("freq"):
        a.rig.set_freq(float(d["freq"]))
    if d.get("mode"):
        a.rig.set_mode(d["mode"], int(d.get("passband") or 0))
    return h.send_json(a.rig.status())


# ------------------------------------------------------------------ VFO / band
JS8_BANDS = {"80": 3578000, "40": 7078000, "30": 10130000, "20": 14078000, "15": 21078000, "10": 28078000}


@route("GET", r"/api/vfo")
def vfo(h):
    """Current dial frequency: from rigctld if enabled, else from JS8Call."""
    a = A(h)
    out = {"source": None, "freq": None, "mode": "", "ptt": False, "error": None,
           "js8": None, "bands": JS8_BANDS}
    if a.js8.connected():
        a.js8.maybe_poll()
        out["js8"] = {"dial": a.js8.info.get("dial"), "offset": a.js8.info.get("offset")}
    if a.db.get("rig_enabled") == "1":
        st = a.rig.status()
        if st.get("ok"):
            out.update(source="rigctld", freq=st["freq"], mode=st["mode"], ptt=st["ptt"])
        else:
            out["error"] = st.get("error")
    if out["freq"] is None and out["js8"] and out["js8"]["dial"]:
        out.update(source="JS8Call", freq=out["js8"]["dial"])
    if out["freq"] is None and not out["error"]:
        out["error"] = "No radio: enable rigctld or JS8Call in Settings"
    return h.send_json(out)


@route("POST", r"/api/js8/band")
def js8_band(h):
    """Tune to the JS8 calling frequency on a band (through JS8Call if connected, else rigctld)."""
    a = A(h)
    band = str(h.body().get("band", ""))
    hz = JS8_BANDS.get(band)
    if not hz:
        raise ValueError("Unknown band %s" % band)
    used = []
    if a.js8.connected():
        a.js8.set_freq(dial_hz=hz)
        used.append("JS8Call")
    elif a.db.get("rig_enabled") == "1":
        a.rig.set_freq(hz)
        a.rig.set_data_usb()
        used.append("rigctld")
    else:
        raise ValueError("No radio control: enable JS8Call or rigctld in Settings")
    net = a.net_or_none()
    if net:
        a.db.log(net["id"], "radio", "Tuned to JS8 %sm: %.3f MHz" % (band, hz / 1e6))
    return h.send_json({"ok": True, "freq": hz, "via": used})


@route("POST", r"/api/js8/offset")
def js8_offset(h):
    a = A(h)
    off = int(h.body().get("offset", 0))
    if not 100 <= off <= 3000:
        raise ValueError("Offset must be 100-3000 Hz")
    a.js8.set_freq(offset_hz=off)
    return h.send_json({"ok": True, "offset": off})


# ------------------------------------------------------------------ reports
@route("GET", r"/api/report/(\d+)")
def report_get(h, nid):
    a = A(h)
    html_ = report.build(a.db, int(nid))
    extra = {}
    if h.query().get("download"):
        extra["Content-Disposition"] = 'attachment; filename="net-%s-summary.html"' % nid
    return h.send_text(html_, extra=extra)


def serve(host="127.0.0.1", port=8073, data_dir=None):
    data_dir = data_dir or os.path.join(os.path.expanduser("~"), ".local", "share", "ares-console")
    os.makedirs(data_dir, exist_ok=True)
    Handler.app = App(data_dir, host, port)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    Handler.httpd = httpd
    print("ARES Console running at http://%s:%d/  (data: %s)" % (host, port, data_dir))
    print("Close this window or use Settings > Quit to stop it.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
