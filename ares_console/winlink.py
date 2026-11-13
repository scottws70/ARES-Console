"""Winlink mailbox, connection manager, transports and gateway list."""
import os
import re
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone

from . import b2f
from .ardop import Ardop
from .db import now
from .events import bus


class TelnetTransport:
    """Telnet to Winlink CMS (cms.winlink.org:8772) or a P2P telnet station."""

    def __init__(self, host, port, mycall, password="CMSTelnet", log=None):
        self.s = socket.create_connection((host, int(port)), timeout=20)
        self.log = log or (lambda s: None)
        self.pre = b""
        # Answer the "Callsign :" and "Password :" prompts, keep anything after them.
        self.pre = self._answer(b"callsign", mycall)
        if b"password" in self.pre.lower() or not self.pre:
            self.pre = self._answer(b"password", password, initial=self.pre)

    def _answer(self, prompt, reply, initial=b""):
        buf = initial
        deadline = time.time() + 30
        while prompt not in buf.lower():
            if b"[" in buf:  # already in B2F handshake, no prompt coming
                return buf
            if time.time() > deadline:
                raise ConnectionError("telnet login: no %s prompt" % prompt.decode())
            self.s.settimeout(5)
            try:
                d = self.s.recv(1024)
            except socket.timeout:
                continue
            if not d:
                raise ConnectionError("telnet closed during login")
            buf += d
        i = buf.lower().find(prompt)
        j = buf.find(b"\r", i)
        rest = buf[j + 1:] if j >= 0 else b""
        self.s.sendall(reply.encode() + b"\r")
        return rest

    def read(self, n, timeout):
        if self.pre:
            out, self.pre = self.pre[:n], self.pre[n:]
            return out
        self.s.settimeout(timeout)
        try:
            d = self.s.recv(n)
            return d if d else None
        except socket.timeout:
            return b""
        except OSError:
            return None

    def write(self, data):
        self.s.sendall(data)

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


class Winlink:
    def __init__(self, db, rig):
        self.db = db
        self.rig = rig
        self.thread = None
        self.session = None
        self.transport = None
        self.state = "idle"
        self.log_lines = []
        self.selection_event = threading.Event()
        self.selection = None
        self.awaiting = None  # list of proposals awaiting operator choice
        self.abort_flag = False

    # ------------------------------------------------------------ logging
    def log(self, s):
        line = "%s %s" % (datetime.now(timezone.utc).strftime("%H:%M:%S"), s)
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-500:]
        bus.publish("winlink_log", line)

    def set_state(self, s):
        self.state = s
        bus.publish("winlink_status", self.status())

    def status(self):
        return {"state": self.state, "awaiting": self.awaiting, "busy": bool(self.thread and self.thread.is_alive())}

    # ------------------------------------------------------------ mailbox
    def compose(self, to, cc, subject, body, net_id=None, form_id=None, attachments=None, via="winlink"):
        mycall = (self.db.get("mycall") or "N0CALL").upper()
        mid = b2f.new_mid()
        to_l = [t.strip() for t in re.split(r"[;,\s]+", to or "") if t.strip()]
        cc_l = [t.strip() for t in re.split(r"[;,\s]+", cc or "") if t.strip()]
        if not to_l:
            raise ValueError("At least one recipient is required")
        raw = b2f.build_message(mid, mycall, to_l, cc_l, subject or "(no subject)", body or "",
                                attachments=attachments)
        mid_id = self.db.insert("messages", {
            "mid": mid, "net_id": net_id, "box": "outbox", "from_addr": mycall,
            "to_addrs": ", ".join(to_l), "cc_addrs": ", ".join(cc_l), "subject": subject,
            "date": now(), "body": body, "raw": raw, "size": len(raw), "created_at": now(),
            "via": via, "status": "queued", "form_id": form_id})
        if net_id:
            self.db.log(net_id, "winlink", "Winlink message queued to %s: %s" % (", ".join(to_l), subject))
        bus.publish("messages", {})
        return mid_id

    def _outbox(self):
        return [{"mid": r["mid"], "subject": r["subject"] or "", "raw": bytes(r["raw"])}
                for r in self.db.q("SELECT mid, subject, raw FROM messages WHERE box='outbox' ORDER BY id")]

    def _on_sent(self, mid):
        self.db.x("UPDATE messages SET box='sent', status='sent', date=? WHERE mid=?", (now(), mid))
        r = self.db.one("SELECT net_id, subject, to_addrs FROM messages WHERE mid=?", (mid,))
        net = self.db.active_net()
        if net:
            self.db.log(net["id"], "winlink", "Winlink message SENT to %s: %s" % (r["to_addrs"], r["subject"]))
        self.log("Message %s delivered" % mid)
        bus.publish("messages", {})

    def _on_received(self, mid, raw):
        m = b2f.parse_message(raw)
        net = self.db.active_net()
        self.db.insert("messages", {
            "mid": mid, "net_id": net["id"] if net else None, "box": "inbox",
            "from_addr": m["from"], "to_addrs": ", ".join(m["to"]), "cc_addrs": ", ".join(m["cc"]),
            "subject": m["subject"], "date": m["date"], "body": m["body"], "raw": raw,
            "size": len(raw), "created_at": now(), "via": "winlink", "status": "unread", "form_id": None})
        self.db.x("DELETE FROM pending WHERE mid=?", (mid,))
        if net:
            self.db.log(net["id"], "winlink", "Winlink message RECEIVED from %s: %s" % (m["from"], m["subject"]))
        self.log("Received %s from %s: %s" % (mid, m["from"], m["subject"]))
        bus.publish("messages", {})

    def _selector(self, gateway):
        def select(props):
            for p in props:
                self.db.x("""INSERT OR REPLACE INTO pending (mid, from_addr, subject, size, gateway, seen_at)
                             VALUES (?,?,?,?,?,?)""",
                          (p["mid"], p.get("from", ""), p.get("subject", ""), p["usize"], gateway, now()))
            auto = self.mode_auto
            if auto == "all":
                return {p["mid"]: "+" for p in props}
            if auto == "none":
                return {p["mid"]: "=" for p in props}
            if auto == "list":
                return {p["mid"]: ("+" if p["mid"] in self.preselect else "=") for p in props}
            # interactive: let the operator choose
            self.awaiting = props
            self.selection = None
            self.selection_event.clear()
            self.set_state("awaiting selection")
            self.log("%d message(s) waiting. Choose which to download." % len(props))
            timeout = int(self.db.get("winlink_select_timeout") or 120)
            self.selection_event.wait(timeout)
            sel = self.selection
            self.awaiting = None
            if sel is None:
                self.log("No selection made in time - all messages deferred (left on server)")
                sel = {p["mid"]: "=" for p in props}
            self.set_state("transferring")
            return sel
        return select

    def choose(self, choices):
        """choices: dict mid -> '+' download, '=' leave on server, '-' reject/delete."""
        self.selection = {k: v for k, v in choices.items() if v in "+=-"}
        self.selection_event.set()

    # ------------------------------------------------------------ sessions
    def start(self, transport, gateway, freq_khz=None, mode="interactive", preselect=None,
              host=None, port=None):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("A Winlink session is already running")
        self.abort_flag = False
        self.mode_auto = mode
        self.preselect = set(preselect or [])
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       args=(transport, gateway, freq_khz, host, port))
        self.thread.start()

    def abort(self):
        self.abort_flag = True
        if self.session:
            self.session.aborted = True
        self.selection_event.set()
        t = self.transport
        if t is not None:
            try:
                if hasattr(t, "abort"):
                    t.abort()
                else:
                    t.close()
            except Exception:  # noqa
                pass
        self.log("Abort requested")

    def _ptt(self, on):
        if self.db.get("ardop_ptt_via_rig") == "1":
            self.rig.ptt(on)

    def _run(self, transport, gateway, freq_khz, host, port):
        mycall = (self.db.get("mycall") or "").upper()
        password = self.db.settings(include_secret=True).get("winlink_password", "")
        grid = self.db.get("grid")
        net = self.db.active_net()
        t = None
        try:
            if not mycall:
                raise RuntimeError("Set your callsign in Settings first")
            gateway = (gateway or "").upper()
            if transport == "ardop":
                if not gateway:
                    raise RuntimeError("Choose a gateway")
                if freq_khz and self.db.get("rig_enabled") == "1":
                    try:
                        self.rig.set_freq(float(freq_khz) * 1000)
                        self.rig.set_data_usb()
                        self.log("Rig set to %.1f kHz" % float(freq_khz))
                    except Exception as e:  # noqa
                        self.log("Rig control failed: %s (continuing)" % e)
                self.set_state("opening ARDOP TNC")
                t = Ardop(self.db.get("ardop_host"), int(self.db.get("ardop_port") or 8515), mycall,
                          grid, self.db.get("ardop_bw") or "2000MAX", ptt_cb=self._ptt, log=self.log)
                self.transport = t
                t.open()
                self.set_state("calling %s" % gateway)
                self.log("Connecting to %s via ARDOP..." % gateway)
                t.connect(gateway, abort_check=lambda: self.abort_flag)
                target = gateway
            elif transport == "telnet":
                host = host or "cms.winlink.org"
                port = port or 8772
                self.set_state("connecting to %s" % host)
                self.log("Telnet to %s:%s" % (host, port))
                t = TelnetTransport(host, port, mycall,
                                    password="CMSTelnet" if "winlink.org" in host else "", log=self.log)
                self.transport = t
                target = gateway or ("CMS" if "winlink.org" in host else host)
            else:
                raise RuntimeError("Unknown transport %s" % transport)
            self.set_state("connected - exchanging")
            if net:
                self.db.log(net["id"], "winlink", "Winlink session opened with %s via %s" % (target, transport))
            self.session = b2f.B2FSession(
                t, mycall, target, password=password, locator=grid, outbox=self._outbox(),
                selector=self._selector(target), on_received=self._on_received, on_sent=self._on_sent,
                log=self.log)
            self.session.run()
            self.log("Session complete")
            if isinstance(t, Ardop):
                t.disconnect()
            self.set_state("idle")
        except Exception as e:  # noqa
            self.log("ERROR: %s" % e)
            self.set_state("idle (error: %s)" % e)
            if isinstance(t, Ardop):
                try:
                    t.abort()
                except Exception:  # noqa
                    pass
        finally:
            if t is not None:
                try:
                    t.close()
                except Exception:  # noqa
                    pass
            if net:
                self.db.log(net["id"], "winlink", "Winlink session ended (%s)" % self.state)
            self.session = None
            self.transport = None
            self.awaiting = None
            bus.publish("messages", {})


# ---------------------------------------------------------------- gateway list

def import_pat_rmslist(db, mode="ardop", force=False):
    args = ["pat", "rmslist", "-m", mode]
    if force:
        args.insert(2, "-d")
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=90).stdout
    except FileNotFoundError:
        raise ValueError("Pat is not installed (needed to download the gateway list). "
                         "Install Pat from getpat.io, or add gateways by hand.")
    n = 0
    db.x("DELETE FROM nodes WHERE source='pat' AND favorite=0")
    for line in out.splitlines():
        m = re.match(r"(\S+)\s+\[(\w*)\]\s+(\d+)\s+(\d+)\s+(.*?)\s{2,}([\d.]+) MHz\s+([\d.]+) MHz\s+(\d+)%\s+(\S+)", line)
        if not m:
            continue
        call, grid, dist, az, modes, dial, center, qual, url = m.groups()
        fm = re.search(r"freq=([\d.]+)", url)
        freq = fm.group(1) if fm else dial
        bw = re.search(r"bw=(\w+)", url)
        if db.one("SELECT 1 FROM nodes WHERE callsign=? AND frequency=?", (call, freq)):
            continue
        db.insert("nodes", {"callsign": call, "frequency": freq, "mode": modes.strip(),
                            "bandwidth": bw.group(1) if bw else "", "grid": grid,
                            "location": "%s km @ %s°" % (dist, az), "hours": "", "notes": "",
                            "source": "pat", "favorite": 0})
        n += 1
    return n


def default_forms_dir(db, base_dir):
    d = db.get("wl_forms_dir")
    if d and os.path.isdir(d):
        return d
    local = os.environ.get("LOCALAPPDATA", "")
    for cand in (os.path.join(base_dir, "Standard_Forms"),
                 os.path.expanduser("~/.local/share/pat/Standard_Forms"),
                 os.path.expanduser("~/Library/Application Support/pat/Standard_Forms"),
                 os.path.join(local, "pat", "Standard_Forms") if local else "",
                 r"C:\RMS Express\Standard Templates"):
        if not cand:
            continue
        if os.path.isdir(cand):
            return cand
    return ""
