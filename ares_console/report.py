"""Net summary / after-action report."""
import html
import json
from datetime import datetime

from . import forms as formdefs

E = html.escape


def _dt(s):
    if not s:
        return ""
    try:
        d = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        return d.strftime("%Y-%m-%d %H:%MZ")
    except ValueError:
        return s


def _dur(a, b):
    try:
        da = datetime.strptime(a, "%Y-%m-%dT%H:%M:%SZ")
        db_ = datetime.strptime(b, "%Y-%m-%dT%H:%M:%SZ")
        m = int((db_ - da).total_seconds() // 60)
        return "%dh %02dm" % (m // 60, m % 60)
    except (TypeError, ValueError):
        return ""


def build(db, net_id):
    s = db.settings()
    net = db.one("SELECT * FROM nets WHERE id=?", (net_id,))
    if not net:
        raise KeyError("net not found")
    checkins = db.q("SELECT * FROM checkins WHERE net_id=? ORDER BY time_in", (net_id,))
    acts = db.q("SELECT * FROM activity WHERE net_id=? ORDER BY ts, id", (net_id,))
    frms = db.q("SELECT * FROM forms WHERE net_id=? ORDER BY created_at", (net_id,))
    msgs = db.q("SELECT id, mid, box, from_addr, to_addrs, subject, date, body, via FROM messages "
                "WHERE net_id=? ORDER BY created_at", (net_id,))
    marks = db.q("SELECT * FROM markers WHERE net_id=? ORDER BY id", (net_id,))
    js8 = db.q("SELECT * FROM js8 WHERE net_id=? ORDER BY ts", (net_id,))
    stations = {r["callsign"]: r for r in db.q("SELECT * FROM stations")}

    counts = {}
    for c in checkins:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    sent = sum(1 for m in msgs if m["box"] == "sent")
    recv = sum(1 for m in msgs if m["box"] == "inbox")
    queued = sum(1 for m in msgs if m["box"] == "outbox")
    end = net["closed_at"] or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    h = []
    h.append("""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Net Summary - %s</title><style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:24px;color:#111;background:#fff;max-width:1100px}
h1{margin:0;font-size:24px}h2{border-bottom:2px solid #333;padding-bottom:4px;margin-top:28px;font-size:18px}
.sub{color:#555;margin:2px 0 16px}table{border-collapse:collapse;width:100%%;font-size:13px}
th,td{border:1px solid #bbb;padding:4px 6px;text-align:left;vertical-align:top}th{background:#eee}
.kv td:first-child{font-weight:600;width:200px;background:#f6f6f6}.stats{display:flex;gap:12px;flex-wrap:wrap}
.stat{border:1px solid #bbb;padding:8px 14px;border-radius:6px;min-width:110px}.stat b{display:block;font-size:22px}
pre{white-space:pre-wrap;font-size:12px;background:#f7f7f7;border:1px solid #ddd;padding:8px}
.noprint{margin-bottom:16px}@media print{.noprint{display:none}body{margin:0}h2{page-break-after:avoid}.form{page-break-inside:avoid}}
</style></head><body>""" % E(net["name"] or ""))
    h.append('<div class="noprint"><button onclick="window.print()">Print / Save as PDF</button></div>')
    h.append("<h1>%s</h1><div class='sub'>%s - Net Summary Report</div>" % (E(s["org_title"]), E(s["org_subtitle"])))
    h.append("<table class='kv'>")
    for k, v in (("Net", net["name"]), ("Net Control", net["ncs"]), ("Frequency", net["frequency"]),
                 ("Opened", _dt(net["opened_at"])), ("Closed", _dt(net["closed_at"]) or "(still open)"),
                 ("Duration", _dur(net["opened_at"], end)), ("Notes", net["notes"]),
                 ("Report generated", datetime.utcnow().strftime("%Y-%m-%d %H:%MZ"))):
        h.append("<tr><td>%s</td><td>%s</td></tr>" % (E(k), E(v or "")))
    h.append("</table>")

    h.append("<h2>Summary</h2><div class='stats'>")
    stats = [("Stations checked in", len(checkins))] + sorted(counts.items()) + [
        ("Log entries", len(acts)), ("Forms", len(frms)), ("Winlink sent", sent),
        ("Winlink received", recv), ("Winlink unsent", queued), ("JS8 directed", len(js8)),
        ("Map locations", len(marks))]
    for k, v in stats:
        h.append("<div class='stat'><b>%s</b>%s</div>" % (v, E(k)))
    h.append("</div>")

    h.append("<h2>Station Roster</h2><table><tr><th>#</th><th>Callsign</th><th>Name</th><th>Tactical</th>"
             "<th>Status</th><th>Location</th><th>Last Position</th><th>Notes</th><th>In</th><th>Out</th></tr>")
    for i, c in enumerate(checkins, 1):
        st = None
        for call, r in stations.items():
            if call.split("-")[0] == (c["callsign"] or "").upper().split("-")[0]:
                if not st or (r["ts"] or "") > (st["ts"] or ""):
                    st = r
        pos = "%.4f, %.4f (%s)" % (st["lat"], st["lon"], _dt(st["ts"])) if st else ""
        h.append("<tr><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                 "<td>%s</td><td>%s</td></tr>" % (
                     i, E(c["callsign"] or ""), E(c["name"] or ""), E(c["tactical"] or ""), E(c["status"] or ""),
                     E(c["location"] or ""), E(pos), E(c["notes"] or ""), _dt(c["time_in"]), _dt(c["time_out"])))
    h.append("</table>")

    if marks:
        h.append("<h2>Map Locations</h2><table><tr><th>Label</th><th>Type</th><th>Lat/Lon</th><th>Notes</th></tr>")
        for m in marks:
            h.append("<tr><td>%s</td><td>%s</td><td>%.5f, %.5f</td><td>%s</td></tr>" % (
                E(m["label"] or ""), E(m["kind"] or ""), m["lat"], m["lon"], E(m["notes"] or "")))
        h.append("</table>")

    h.append("<h2>Activity Log</h2><table><tr><th>Time</th><th>Type</th><th>Station</th><th>Entry</th></tr>")
    for a in acts:
        h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            _dt(a["ts"]), E(a["kind"] or ""), E(a["callsign"] or ""), E(a["text"] or "")))
    h.append("</table>")

    if msgs:
        h.append("<h2>Winlink Traffic</h2><table><tr><th>Date</th><th>Box</th><th>From</th><th>To</th>"
                 "<th>Subject</th><th>MID</th></tr>")
        for m in msgs:
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                E(_dt(m["date"]) or ""), E(m["box"]), E(m["from_addr"] or ""), E(m["to_addrs"] or ""),
                E(m["subject"] or ""), E(m["mid"] or "")))
        h.append("</table>")

    if js8:
        h.append("<h2>JS8Call Traffic</h2><table><tr><th>Time</th><th>Dir</th><th>From</th><th>To</th><th>Text</th></tr>")
        for j in js8:
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _dt(j["ts"]), E(j["kind"] or ""), E(j["from_call"] or ""), E(j["to_call"] or ""), E(j["text"] or "")))
        h.append("</table>")

    if frms:
        h.append("<h2>Forms &amp; Messages</h2><table><tr><th>Created</th><th>Form</th><th>Title</th><th>Direction</th></tr>")
        for fr in frms:
            h.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                _dt(fr["created_at"]), E(form_name(fr["form_type"])), E(fr["title"] or ""), E(fr["direction"] or "")))
        h.append("</table><h2>Form Contents</h2>")
        for fr in frms:
            h.append("<div class='form'><h3>%s - %s</h3><pre>%s</pre></div>" % (
                E(form_name(fr["form_type"])), E(fr["title"] or ""), E(form_text(fr, s))))
    h.append("</body></html>")
    return "\n".join(h)


def form_name(ft):
    if ft in formdefs.FORMS:
        return formdefs.FORMS[ft]["name"]
    if ft.startswith("WL:"):
        return "Winlink: " + ft[3:].split("/")[-1].rsplit(".", 1)[0]
    if ft.startswith("MCF:"):
        return "MCForm " + ft[4:]
    return ft


def form_text(fr, settings):
    data = json.loads(fr["data"] or "{}")
    ft = fr["form_type"]
    if ft in formdefs.FORMS:
        return formdefs.render_text(ft, data, settings.get("org_title", ""))
    if ft.startswith("WL:"):
        return "Subject: %s\n\n%s" % (data.get("subject", ""), data.get("body", ""))
    if ft.startswith("MCF:"):
        return data.get("compact", "") + "\n\n" + data.get("readable", "")
    return json.dumps(data, indent=2)
