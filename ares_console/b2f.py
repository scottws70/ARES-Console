"""Winlink B2F (FBB B2 forwarding) client session.

Transport-agnostic: works over any object providing
    read(n, timeout) -> bytes   (blocking until >=1 byte or timeout -> b'')
    write(data: bytes)
    flush()  (wait for outbound data to be transmitted; optional)
Used over ARDOP ARQ and over Telnet (CMS internet fallback / P2P testing).
"""
import hashlib
import random
import re
import string
import time
from datetime import datetime, timezone

from . import lzhuf

SID_NAME = "ARESConsole"
SID_VERSION = "1.0"
SID_FEATURES = "B2FHM$"

SOH, STX, EOT = 0x01, 0x02, 0x04

# Winlink secure-login salt (public, from the Winlink/FBB spec as implemented by Pat/wl2k-go)
_SALT = bytes([
    77, 197, 101, 206, 190, 249, 93, 200, 51, 243, 93, 237, 71, 94, 239, 138,
    68, 108, 70, 185, 225, 137, 217, 16, 51, 122, 193, 48, 194, 195, 198, 175,
    172, 169, 70, 84, 61, 62, 104, 186, 114, 52, 61, 168, 66, 129, 192, 208,
    187, 249, 232, 193, 41, 113, 41, 45, 240, 16, 29, 228, 208, 228, 61, 20,
])


class B2FError(Exception):
    pass


def secure_login_response(challenge: str, password: str) -> str:
    s = hashlib.md5(challenge.encode() + password.encode() + _SALT).digest()
    pr = ((s[3] & 0x3F) << 24) | (s[2] << 16) | (s[1] << 8) | s[0]
    txt = "%08d" % pr
    return txt[-8:]


def new_mid() -> str:
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(12))


def proposal_checksum(lines):
    total = 0
    for ln in lines:
        for b in (ln + "\r").encode("latin-1"):
            total += b
    return "%02X" % ((-total) & 0xFF)


# ---------------------------------------------------------------- messages

def build_message(mid, from_addr, to_list, cc_list, subject, body, mbo=None, attachments=None, date=None):
    """Build a Winlink message (RFC-ish header + body + attachments) as bytes."""
    attachments = attachments or []
    date = date or datetime.now(timezone.utc)
    body_b = body.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    hdr = [
        "Mid: " + mid,
        "Body: %d" % len(body_b),
        "Content-Transfer-Encoding: 8bit",
        "Content-Type: text/plain; charset=UTF-8",
        "Date: " + date.strftime("%Y/%m/%d %H:%M"),
        "From: " + from_addr,
        "Mbo: " + (mbo or from_addr),
        "Subject: " + subject,
        "Type: Private",
    ]
    for t in to_list:
        hdr.append("To: " + t)
    for c in cc_list:
        hdr.append("Cc: " + c)
    for name, data in attachments:
        hdr.append("File: %d %s" % (len(data), name))
    out = ("\r\n".join(hdr) + "\r\n\r\n").encode("utf-8") + body_b + b"\r\n"
    for name, data in attachments:
        out += data + b"\r\n"
    return out


def parse_message(raw: bytes):
    sep = raw.find(b"\r\n\r\n")
    if sep < 0:
        sep = raw.find(b"\n\n")
        hdr_txt, rest = raw[:sep], raw[sep + 2:]
    else:
        hdr_txt, rest = raw[:sep], raw[sep + 4:]
    headers = []
    for line in hdr_txt.decode("utf-8", "replace").splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            headers.append((k.strip(), v.strip()))
    h = {}
    for k, v in headers:
        h.setdefault(k.lower(), []).append(v)
    blen = int(h.get("body", ["0"])[0] or 0) if h.get("body") else len(rest)
    body = rest[:blen].decode("utf-8", "replace")
    pos = blen + 2
    files = []
    for f in h.get("file", []):
        m = re.match(r"(\d+)\s+(.*)", f)
        if not m:
            continue
        size, name = int(m.group(1)), m.group(2)
        files.append({"name": name, "data": rest[pos:pos + size]})
        pos += size + 2
    return {
        "mid": (h.get("mid") or [""])[0],
        "from": (h.get("from") or [""])[0],
        "to": h.get("to", []),
        "cc": h.get("cc", []),
        "subject": (h.get("subject") or [""])[0],
        "date": (h.get("date") or [""])[0],
        "body": body,
        "files": files,
        "headers": headers,
    }


# ---------------------------------------------------------------- session

class B2FSession:
    """Client-side (non-master) B2F exchange.

    outbox:   list of dicts {mid, subject, raw(bytes)}
    selector: callable(list_of_proposals) -> dict mid -> '+', '-', '='
              proposals: {mid, usize, csize, from, subject, to}
    on_received(mid, raw_bytes), on_sent(mid), log(str)
    """

    def __init__(self, transport, mycall, target, password=None, locator="",
                 outbox=None, selector=None, on_received=None, on_sent=None, log=None,
                 timeout=180):
        self.t = transport
        self.mycall = mycall.upper()
        self.target = target.upper()
        self.password = password or ""
        self.locator = locator
        self.outbox = list(outbox or [])
        self.selector = selector or (lambda props: {p["mid"]: "+" for p in props})
        self.on_received = on_received or (lambda mid, raw: None)
        self.on_sent = on_sent or (lambda mid: None)
        self.log = log or (lambda s: None)
        self.timeout = timeout
        self._buf = bytearray()
        self.pending_info = {}  # mid -> {from, subject, to, size} from ;PM lines
        self.aborted = False

    # --- low-level io
    def _fill(self):
        deadline = time.time() + self.timeout
        while True:
            if self.aborted:
                raise B2FError("aborted")
            data = self.t.read(4096, 1.0)
            if data:
                self._buf += data
                return
            if data is None:
                raise B2FError("connection closed")
            if time.time() > deadline:
                raise B2FError("timeout waiting for data")

    def readline(self):
        while True:
            # drop leading line terminators
            while self._buf and self._buf[0] in (0x0D, 0x0A):
                del self._buf[0]
            idx = [i for i in (self._buf.find(b"\r"), self._buf.find(b"\n")) if i >= 0]
            if not idx:
                self._fill()
                continue
            i = min(idx)
            line = bytes(self._buf[:i])
            del self._buf[:i + 1]
            txt = line.decode("latin-1")
            self.log("< " + txt)
            return txt

    def readbytes(self, n):
        while len(self._buf) < n:
            self._fill()
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    def send(self, text):
        for ln in text.split("\r"):
            if ln:
                self.log("> " + ln)
        self.t.write(text.encode("latin-1"))

    # --- protocol
    def run(self):
        self._handshake()
        remote_ff = False
        while True:
            # our turn
            batch = self.outbox[:5]
            if batch:
                self._send_proposals(batch)
                remote_ff = False
            else:
                if remote_ff:
                    self.send("FQ\r")
                    self._flush()
                    return
                self.send("FF\r")
            # remote's turn
            while True:
                line = self.readline()
                if line.startswith(";"):
                    self._parse_comment(line)
                    continue
                if line.startswith("***"):
                    raise B2FError(line)
                break
            if line.startswith("FQ"):
                return
            if line.startswith("FF"):
                remote_ff = True
                continue
            if line.startswith("FC") or line.startswith("FA") or line.startswith("FB"):
                self._receive_proposals(line)
                remote_ff = False
                continue
            raise B2FError("unexpected line from remote: " + line)

    def _flush(self):
        if hasattr(self.t, "flush"):
            self.t.flush()

    def _parse_comment(self, line):
        m = re.match(r";PM:\s*(\S+)\s+(\S+)\s+(\d+)\s+(\S+)\s*(.*)", line)
        if m:
            self.pending_info[m.group(2)] = {
                "to": m.group(1), "size": int(m.group(3)),
                "from": m.group(4), "subject": m.group(5).strip(),
            }

    def _handshake(self):
        challenge = None
        sid_seen = False
        while True:
            line = self.readline()
            if line.startswith("***"):
                raise B2FError(line)
            if line.startswith("[") and line.endswith("]"):
                sid_seen = True
                if "B2F" not in line.upper():
                    raise B2FError("remote does not support B2F: " + line)
            elif line.startswith(";PQ:"):
                challenge = line[4:].strip()
            elif line.startswith(";"):
                self._parse_comment(line)
            if line.endswith(">") and sid_seen:
                break
        out = ";FW: %s\r" % self.mycall
        out += "[%s-%s-%s]\r" % (SID_NAME, SID_VERSION, SID_FEATURES)
        if challenge:
            if not self.password:
                raise B2FError("gateway requested secure login but no Winlink password is set")
            out += ";PR: %s\r" % secure_login_response(challenge, self.password)
        out += "; %s DE %s (%s)\r" % (self.target, self.mycall, self.locator or "")
        self.send(out)

    def _send_proposals(self, batch):
        lines = []
        comp = []
        for m in batch:
            c = lzhuf.compress_b2(m["raw"])
            comp.append(c)
            lines.append("FC EM %s %d %d 0" % (m["mid"], len(m["raw"]), len(c)))
        txt = "".join(l + "\r" for l in lines) + "F> %s\r" % proposal_checksum(lines)
        self.send(txt)
        line = self.readline()
        while line.startswith(";"):
            line = self.readline()
        if line.startswith("***"):
            raise B2FError(line)
        if not line.startswith("FS"):
            raise B2FError("expected FS, got " + line)
        answers = self._parse_fs(line[2:].strip())
        if len(answers) != len(batch):
            raise B2FError("FS answer count mismatch: " + line)
        for m, c, (ans, offset) in zip(batch, comp, answers):
            if ans == "+":
                self._send_block(m["subject"], c[offset:] if offset else c, offset)
            self.outbox.remove(m)
        self._flush()
        for m, (ans, _o) in zip(batch, answers):
            if ans in "+-":
                self.on_sent(m["mid"])

    @staticmethod
    def _parse_fs(s):
        out = []
        i = 0
        s = s.replace(" ", "")
        while i < len(s):
            ch = s[i].upper()
            i += 1
            if ch in "+Y":
                ans = "+"
            elif ch in "-NR":
                ans = "-"
            elif ch in "=L":
                ans = "="
            elif ch in "!A":
                ans = "+"
                m = re.match(r"\d+", s[i:])
                off = int(m.group(0)) if m else 0
                i += len(m.group(0)) if m else 0
                out.append((ans, off))
                continue
            elif ch == "H":
                ans = "="
            else:
                continue
            out.append((ans, 0))
        return out

    def _send_block(self, subject, data, offset=0):
        title = subject.encode("latin-1", "replace")[:80]
        hdr = title + b"\x00" + str(offset).encode() + b"\x00"
        pkt = bytearray([SOH, len(hdr)]) + hdr
        total = 0
        for i in range(0, len(data), 250):
            chunk = data[i:i + 250]
            pkt += bytes([STX, len(chunk) & 0xFF]) + chunk
            total += sum(chunk)
        pkt += bytes([EOT, (-total) & 0xFF])
        self.log("> [binary block %d bytes: %s]" % (len(data), subject))
        self.t.write(bytes(pkt))

    def _receive_proposals(self, first):
        props = []
        lines = []
        line = first
        while True:
            if line.startswith("F>"):
                chk = line[2:].strip()
                if chk and chk.upper() != proposal_checksum(lines):
                    raise B2FError("proposal checksum mismatch")
                break
            if line.startswith(";"):
                self._parse_comment(line)
            elif line.startswith("F"):
                lines.append(line)
                parts = line.split()
                if parts[0] == "FC" and len(parts) >= 5:
                    props.append({"type": parts[1], "mid": parts[2],
                                  "usize": int(parts[3]), "csize": int(parts[4])})
                else:
                    props.append({"type": "?", "mid": parts[1] if len(parts) > 1 else "?",
                                  "usize": 0, "csize": 0, "unsupported": True})
            line = self.readline()
        for p in props:
            p.update({k: v for k, v in self.pending_info.get(p["mid"], {}).items() if k != "size"})
        choices = {}
        supported = [p for p in props if not p.get("unsupported") and p["type"] in ("EM", "CM")]
        if supported:
            choices = self.selector(supported) or {}
        answers = []
        for p in props:
            if p.get("unsupported") or p["type"] not in ("EM", "CM"):
                answers.append("-")
            else:
                answers.append(choices.get(p["mid"], "="))
        self.send("FS %s\r" % "".join(answers))
        for p, a in zip(props, answers):
            if a != "+":
                continue
            data = self._read_block()
            raw = lzhuf.decompress_b2(data)
            self.on_received(p["mid"], raw)

    def _read_block(self):
        b = self.readbytes(1)[0]
        while b in (0x0D, 0x0A):
            b = self.readbytes(1)[0]
        if b != SOH:
            raise B2FError("expected SOH, got 0x%02X" % b)
        hlen = self.readbytes(1)[0]
        hdr = self.readbytes(hlen)
        title = hdr.split(b"\x00")[0].decode("latin-1", "replace")
        data = bytearray()
        total = 0
        while True:
            t = self.readbytes(1)[0]
            if t == STX:
                n = self.readbytes(1)[0] or 256
                chunk = self.readbytes(n)
                data += chunk
                total += sum(chunk)
            elif t == EOT:
                chk = self.readbytes(1)[0]
                if (total + chk) & 0xFF != 0:
                    raise B2FError("block checksum error (%s)" % title)
                self.log("< [binary block %d bytes: %s]" % (len(data), title))
                return bytes(data)
            else:
                raise B2FError("bad block byte 0x%02X" % t)
