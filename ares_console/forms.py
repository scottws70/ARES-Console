"""Built-in fillable forms: ICS-213, ICS-214, ICS-205, ICS-309 and the ARRL/NTS Radiogram."""
import re

T = "text"
TA = "textarea"


def f(k, label, type=T, **kw):
    d = {"k": k, "label": label, "type": type}
    d.update(kw)
    return d


def sec(label):
    return {"type": "section", "label": label}


FORMS = {
    "ICS213": {
        "name": "ICS-213 General Message",
        "category": "ICS",
        "multi": True,
        "fields": [
            f("direction", "Direction", "select", options=["Outgoing", "Incoming"]),
            f("msg_no", "Message #", width=1),
            f("via", "Handled via", "select", options=["Winlink", "Voice", "JS8Call", "NTS", "Runner", "Other"]),
            f("inc_name", "1. Incident Name"),
            f("to", "2. To (Name and Position)"),
            f("from", "3. From (Name and Position)"),
            f("subject", "4. Subject"),
            f("date", "5. Date", "date", auto="date"),
            f("time", "6. Time", "time", auto="time"),
            f("message", "7. Message", TA, rows=10),
            f("approved_name", "8. Approved by: Name"),
            f("approved_sig", "Signature"),
            f("approved_pos", "Position/Title"),
            sec("Reply"),
            f("reply", "9. Reply", TA, rows=5),
            f("replied_name", "10. Replied by: Name"),
            f("replied_pos", "Position/Title"),
            f("replied_sig", "Signature"),
            f("replied_dt", "Date/Time", "datetime-local"),
        ],
        "subject": "ICS-213: {subject}",
    },
    "ICS214": {
        "name": "ICS-214 Activity Log",
        "category": "ICS",
        "fields": [
            f("inc_name", "1. Incident Name"),
            f("op_from", "2. Operational Period From", "datetime-local"),
            f("op_to", "Operational Period To", "datetime-local"),
            f("name", "3. Name", auto="operator"),
            f("position", "4. ICS Position", default="Net Control Station"),
            f("agency", "5. Home Agency (and Unit)", auto="org"),
            f("resources", "6. Resources Assigned", "table",
              cols=[{"k": "name", "label": "Name"}, {"k": "position", "label": "ICS Position"},
                    {"k": "agency", "label": "Home Agency (and Unit)"}], import_from="checkins"),
            f("log", "7. Activity Log", "table",
              cols=[{"k": "dt", "label": "Date/Time", "w": 16}, {"k": "activity", "label": "Notable Activities", "w": 60}],
              import_from="activity"),
            f("prep_name", "8. Prepared by: Name", auto="operator"),
            f("prep_pos", "Position/Title", default="Net Control Station"),
            f("prep_sig", "Signature"),
            f("prep_dt", "Date/Time", "datetime-local"),
        ],
        "subject": "ICS-214 Activity Log: {inc_name}",
    },
    "ICS205": {
        "name": "ICS-205 Incident Radio Communications Plan",
        "category": "ICS",
        "fields": [
            f("inc_name", "1. Incident Name"),
            f("prepared", "2. Date/Time Prepared", "datetime-local"),
            f("op_from", "3. Operational Period From", "datetime-local"),
            f("op_to", "Operational Period To", "datetime-local"),
            f("channels", "4. Basic Radio Channel Use", "table",
              cols=[{"k": "zone", "label": "Zone/Grp"}, {"k": "ch", "label": "Ch #"},
                    {"k": "function", "label": "Function"}, {"k": "name", "label": "Channel Name"},
                    {"k": "assignment", "label": "Assignment"}, {"k": "rx", "label": "RX Freq"},
                    {"k": "rxnw", "label": "N/W"}, {"k": "rxtone", "label": "RX Tone"},
                    {"k": "tx", "label": "TX Freq"}, {"k": "txnw", "label": "N/W"},
                    {"k": "txtone", "label": "TX Tone"}, {"k": "mode", "label": "Mode (A/D/M)"},
                    {"k": "remarks", "label": "Remarks"}]),
            f("special", "5. Special Instructions", TA, rows=4),
            f("prep_name", "6. Prepared by (Comms Unit Leader): Name", auto="operator"),
            f("prep_sig", "Signature"),
        ],
        "subject": "ICS-205 Radio Plan: {inc_name}",
    },
    "ICS309": {
        "name": "ICS-309 Communications Log",
        "category": "ICS",
        "fields": [
            f("inc_name", "1. Incident Name"),
            f("op_from", "2. Operational Period From", "datetime-local"),
            f("op_to", "Operational Period To", "datetime-local"),
            f("radio_op", "3. Radio Operator (Name, Call Sign)", auto="operator_call"),
            f("log", "4. Communications Log", "table",
              cols=[{"k": "time", "label": "Time"}, {"k": "from_call", "label": "From Call"},
                    {"k": "from_msg", "label": "From Msg #"}, {"k": "to_call", "label": "To Call"},
                    {"k": "to_msg", "label": "To Msg #"}, {"k": "message", "label": "Message", "w": 50}],
              import_from="traffic"),
            f("prep_name", "5. Prepared by", auto="operator_call"),
            f("prep_dt", "Date/Time Prepared", "datetime-local"),
        ],
        "subject": "ICS-309 Comms Log: {inc_name}",
    },
    "RADIOGRAM": {
        "name": "NTS Radiogram (ARRL)",
        "category": "NTS",
        "multi": True,
        "fields": [
            f("direction", "Direction", "select", options=["Originated", "Received", "Relayed"]),
            sec("Preamble"),
            f("number", "Number", width=1),
            f("precedence", "Precedence", "select", options=["R", "W", "P", "EMERGENCY"],
              help="R=Routine, W=Welfare, P=Priority"),
            f("hx", "HX", "select", options=["", "HXA", "HXB", "HXC", "HXD", "HXE", "HXF", "HXG"]),
            f("station", "Station of Origin", auto="mycall"),
            f("check", "Check", help="Auto-calculated from the text word count (ARL adds)"),
            f("place", "Place of Origin"),
            f("time_filed", "Time Filed (UTC/Z)", help="e.g. 1530Z"),
            f("date_filed", "Date (e.g. NOV 12)"),
            sec("Addressee"),
            f("to", "To (Name, Address, City/State/ZIP)", TA, rows=3),
            f("phone", "Telephone"),
            f("email", "Email"),
            sec("Message"),
            f("text", "Text (25 words or less recommended; use X for period, QUERY for ?)", TA, rows=4,
              upper=True),
            f("signature", "Signature", TA, rows=2),
            f("op_note", "OP NOTE"),
            sec("Handling"),
            f("rcvd_from", "Received From"),
            f("rcvd_dt", "Received Date/Time"),
            f("sent_to", "Sent To"),
            f("sent_dt", "Sent Date/Time"),
        ],
        "subject": "RADIOGRAM {number} {precedence} {place}",
    },
}


def radiogram_check(text):
    words = [w for w in re.split(r"\s+", (text or "").strip()) if w]
    n = len(words)
    if words and words[0].upper() == "ARL":
        return "ARL %d" % n
    return str(n)


def _fmt_table(field, rows):
    cols = field["cols"]
    widths = []
    for c in cols:
        w = max([len(c["label"])] + [len(str(r.get(c["k"], "") or "")) for r in rows]) if rows else len(c["label"])
        widths.append(min(w, c.get("w", 30)))
    out = ["  " + " | ".join(c["label"].ljust(widths[i]) for i, c in enumerate(cols))]
    out.append("  " + "-+-".join("-" * w for w in widths))
    for r in rows:
        out.append("  " + " | ".join(str(r.get(c["k"], "") or "")[:max(widths[i], 60)].ljust(widths[i])
                                     for i, c in enumerate(cols)))
    return out


def render_text(form_type, data, org=""):
    if form_type == "RADIOGRAM":
        return render_radiogram(data)
    d = FORMS.get(form_type)
    if not d:
        return "\n".join("%s: %s" % (k, v) for k, v in data.items())
    out = [d["name"].upper()]
    if org:
        out.append(org)
    out.append("")
    for fld in d["fields"]:
        if fld["type"] == "section":
            out += ["", "--- %s ---" % fld["label"]]
            continue
        v = data.get(fld["k"], "")
        if fld["type"] == "table":
            rows = [r for r in (v or []) if any(str(x).strip() for x in r.values())]
            out.append(fld["label"] + ":")
            out += _fmt_table(fld, rows)
            continue
        if fld["type"] == TA:
            out.append(fld["label"] + ":")
            out += ["  " + ln for ln in str(v or "").splitlines()] or [""]
        else:
            out.append("%s: %s" % (fld["label"], v or ""))
    return "\n".join(out) + "\n"


def render_radiogram(d):
    text = (d.get("text") or "").upper()
    check = d.get("check") or radiogram_check(text)
    pre = " ".join(x for x in [
        "NR " + str(d.get("number") or ""), d.get("precedence") or "R", d.get("hx") or "",
        (d.get("station") or "").upper(), check, (d.get("place") or "").upper(),
        (d.get("time_filed") or "").upper(), (d.get("date_filed") or "").upper()] if x)
    words = [w for w in text.split() if w]
    lines = [" ".join(words[i:i + 5]) for i in range(0, len(words), 5)]
    out = ["RADIOGRAM - THE AMERICAN RADIO RELAY LEAGUE", "", pre, ""]
    out += [ln.upper() for ln in (d.get("to") or "").splitlines()]
    if d.get("phone"):
        out.append(d["phone"])
    if d.get("email"):
        out.append(d["email"].upper())
    out += ["BT"] + lines + ["BT"]
    out += [ln.upper() for ln in (d.get("signature") or "").splitlines()]
    if d.get("op_note"):
        out.append("OP NOTE " + d["op_note"].upper())
    out.append("AR")
    hand = []
    for k, lab in (("rcvd_from", "RCVD FROM"), ("rcvd_dt", "DATE/TIME"), ("sent_to", "SENT TO"), ("sent_dt", "DATE/TIME")):
        if d.get(k):
            hand.append("%s %s" % (lab, d[k]))
    if hand:
        out += [""] + hand
    return "\n".join(out) + "\n"


def subject_for(form_type, data):
    d = FORMS.get(form_type)
    if not d:
        return form_type
    try:
        return d["subject"].format_map(_Default(data)).strip()
    except Exception:  # noqa
        return d["name"]


class _Default(dict):
    def __missing__(self, k):
        return ""


def title_for(form_type, data):
    if form_type == "ICS213":
        return data.get("subject") or "(no subject)"
    if form_type == "RADIOGRAM":
        return "NR %s %s" % (data.get("number", ""), (data.get("to") or "").split("\n")[0])
    return data.get("inc_name") or FORMS.get(form_type, {}).get("name", form_type)
