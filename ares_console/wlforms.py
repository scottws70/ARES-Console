"""Winlink Standard Forms library support (the same HTML/TXT templates used by Winlink Express and Pat).

Point Settings > Winlink forms folder at a Standard_Forms directory (Pat keeps one at
~/.local/share/pat/Standard_Forms - `pat templates update` refreshes it).
"""
import html
import os
import re
import urllib.parse
from datetime import datetime, timezone
from xml.sax.saxutils import escape as xml_escape
import xml.etree.ElementTree as ET

PROGRAM_VERSION = "ARES Console 1.0"


def _read(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _safe_join(root, rel):
    p = os.path.realpath(os.path.join(root, rel))
    if not p.startswith(os.path.realpath(root) + os.sep):
        raise ValueError("bad path")
    return p


def _find_file(folder, name, root=None):
    """Case-insensitive lookup in folder, then anywhere under root."""
    name = name.strip()
    if not name:
        return None
    try:
        for fn in os.listdir(folder):
            if fn.lower() == name.lower():
                return os.path.join(folder, fn)
    except OSError:
        pass
    if root:
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn.lower() == name.lower():
                    return os.path.join(dp, fn)
    return None


def parse_template(text):
    hdr = {}
    body = ""
    lines = text.replace("\r\n", "\n").split("\n")
    for i, ln in enumerate(lines):
        m = re.match(r"(\w+):(.*)", ln)
        if m and m.group(1).lower() == "msg":
            body = "\n".join([m.group(2)] + lines[i + 1:]) if m.group(2).strip() else "\n".join(lines[i + 1:])
            break
        if m:
            hdr[m.group(1).lower()] = m.group(2).strip()
    return hdr, body


def list_templates(root):
    out = []
    if not root or not os.path.isdir(root):
        return out
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if not fn.lower().endswith(".txt"):
                continue
            p = os.path.join(dp, fn)
            try:
                hdr, _ = parse_template(_read(p))
            except OSError:
                continue
            if "form" not in hdr:
                continue
            rel = os.path.relpath(p, root)
            out.append({"path": rel, "name": fn[:-4], "folder": os.path.relpath(dp, root)})
    out.sort(key=lambda x: (x["folder"].lower(), x["name"].lower()))
    return out


def _sub_common(text, ctx):
    rep = {
        "{MsgSender}": ctx["mycall"], "{Callsign}": ctx["mycall"], "{GridSquare}": ctx["grid"],
        "{Latitude}": ctx["lat"], "{Longitude}": ctx["lon"], "{latitude}": ctx["lat"],
        "{longitude}": ctx["lon"], "{GPS_SIGNED_DECIMAL}": "%s, %s" % (ctx["lat"], ctx["lon"]),
        "{Location_Source}": "SPECIFIED", "{GPSValid}": "NO", "{InternetAvailable}": "NO",
        "{DateTime}": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "{SeqNum}": str(ctx.get("seq", 1)),
        "{decimal_separator}": ".", "{ProgramVersion}": PROGRAM_VERSION,
    }
    for k, v in rep.items():
        text = text.replace(k, v or "")
    return text


def initial_html(root, rel, ctx):
    tpl = _safe_join(root, rel)
    hdr, _ = parse_template(_read(tpl))
    names = [n.strip() for n in hdr.get("form", "").split(",")]
    p = _find_file(os.path.dirname(tpl), names[0], root) if names else None
    if not p:
        raise FileNotFoundError("Initial form HTML not found for %s" % rel)
    doc = _read(p)
    action = "/wlforms/submit?tpl=" + urllib.parse.quote(rel)
    doc = re.sub(r"http://\{FormServer\}:\{FormPort\}[^\"']*", action, doc)
    doc = doc.replace("{FormServer}", ctx["host"]).replace("{FormPort}", str(ctx["port"]))
    doc = _sub_common(doc, ctx)
    # Initial forms start empty, except the sender's callsign.
    doc = re.sub(r"\{var\s+MsgSender\}", ctx["mycall"], doc, flags=re.I)
    doc = re.sub(r"\{var\s+[^}]+\}", "", doc)
    return doc


def _lookup(fields, name):
    if name in fields:
        return fields[name]
    low = name.lower()
    for k, v in fields.items():
        if k.lower() == low:
            return v
    return ""


def fill(template, fields, ctx):
    def var(m):
        return _lookup(fields, m.group(1).strip())
    out = re.sub(r"<var\s+([^>]+)>", var, template, flags=re.I)
    out = out.replace("<MsgSender>", ctx["mycall"]).replace("<Callsign>", ctx["mycall"])
    out = out.replace("<ProgramVersion>", PROGRAM_VERSION)
    out = out.replace("<DateTime>", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    out = out.replace("<MsgTo>", "").replace("<MsgCc>", "")
    return out


def submit(root, rel, fields, ctx):
    tpl = _safe_join(root, rel)
    hdr, body = parse_template(_read(tpl))
    names = [n.strip() for n in hdr.get("form", "").split(",")]
    viewer = names[1] if len(names) > 1 else ""
    to = fill(hdr.get("to", ""), fields, ctx).strip()
    cc = fill(hdr.get("cc", ""), fields, ctx).strip()
    subject = fill(hdr.get("subject", ""), fields, ctx).strip()
    msg = fill(body, fields, ctx).strip("\n") + "\n"
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    vars_xml = "\n".join("    <%s>%s</%s>" % (k, xml_escape(v), k) for k, v in fields.items()
                         if re.fullmatch(r"[A-Za-z_][\w.-]*", k))
    xml = ("<?xml version=\"1.0\"?>\n<RMS_Express_Form>\n  <form_parameters>\n"
           "    <xml_file_version>1.0</xml_file_version>\n"
           "    <rms_express_version>%s</rms_express_version>\n"
           "    <submission_datetime>%s</submission_datetime>\n"
           "    <senders_callsign>%s</senders_callsign>\n"
           "    <grid_square>%s</grid_square>\n"
           "    <display_form>%s</display_form>\n"
           "    <reply_template>%s</reply_template>\n"
           "  </form_parameters>\n  <variables>\n%s\n  </variables>\n</RMS_Express_Form>\n") % (
        PROGRAM_VERSION, ts, ctx["mycall"], ctx["grid"], xml_escape(viewer),
        xml_escape(hdr.get("replytemplate", "")), vars_xml)
    att_name = "RMS_Express_Form_%s.xml" % (os.path.splitext(viewer)[0] or "form").replace(" ", "_")
    return {"to": to, "cc": cc, "subject": subject, "body": msg, "xml": xml, "xml_name": att_name,
            "template": rel, "viewer": viewer}


def render_viewer(root, xml_bytes, ctx):
    """Render a received RMS_Express_Form XML with its viewer HTML, if available."""
    tree = ET.fromstring(xml_bytes)
    params = tree.find("form_parameters")
    viewer = params.findtext("display_form") if params is not None else ""
    variables = {}
    v = tree.find("variables")
    if v is not None:
        for el in v:
            variables[el.tag] = el.text or ""
    p = _find_file(root, viewer, root) if (root and viewer) else None
    if not p:
        rows = "".join("<tr><th>%s</th><td><pre>%s</pre></td></tr>" % (html.escape(k), html.escape(val))
                       for k, val in variables.items())
        return ("<!doctype html><meta charset=utf-8><title>Form</title>"
                "<style>body{font-family:sans-serif}th{text-align:left;vertical-align:top;padding-right:1em}"
                "pre{margin:0;white-space:pre-wrap}</style><h2>%s</h2><p>Viewer form not found in the local "
                "library; showing raw fields.</p><table>%s</table>") % (html.escape(viewer or "Form"), rows)
    doc = _read(p)

    def var(m):
        return html.escape(_lookup(variables, m.group(1).strip()))
    doc = re.sub(r"\{var\s+([^}]+)\}", var, doc)
    doc = _sub_common(doc, ctx)
    return doc
