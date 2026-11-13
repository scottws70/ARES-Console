"""Radio control via Hamlib rigctld (TCP)."""
import socket
import threading
import time


class Rig:
    def __init__(self, db):
        self.db = db
        self.lock = threading.Lock()
        self.sock = None
        self.fail_until = 0

    def _conn(self):
        if self.sock is None:
            if time.time() < self.fail_until:
                raise ConnectionError("rigctld not reachable")
            host = self.db.get("rig_host") or "127.0.0.1"
            port = int(self.db.get("rig_port") or 4532)
            try:
                self.sock = socket.create_connection((host, port), timeout=1.5)
            except OSError as e:
                self.fail_until = time.time() + 5  # don't stall every poll while the rig is off
                raise ConnectionError("rigctld not reachable at %s:%s (%s)" % (host, port, e))
            self.sock.settimeout(3)
        return self.sock

    def cmd(self, c):
        """Send a rigctld command; returns list of response lines."""
        with self.lock:
            for attempt in (1, 2):
                try:
                    s = self._conn()
                    s.sendall((c + "\n").encode())
                    data = b""
                    # rigctld default protocol: get commands return values, set commands return RPRT n
                    while True:
                        chunk = s.recv(1024)
                        if not chunk:
                            raise ConnectionError("rigctld closed")
                        data += chunk
                        lines = data.decode(errors="replace").splitlines()
                        if data.endswith(b"\n") and (lines and (lines[-1].startswith("RPRT") or
                                                                self._complete(c, lines))):
                            return lines
                except (OSError, ConnectionError):
                    try:
                        if self.sock:
                            self.sock.close()
                    except OSError:
                        pass
                    self.sock = None
                    if attempt == 2:
                        raise

    @staticmethod
    def _complete(c, lines):
        need = {"f": 1, "m": 2, "t": 1}.get(c.split()[0], 1)
        return len(lines) >= need

    def status(self):
        try:
            f = self.cmd("f")
            m = self.cmd("m")
            ptt = self.cmd("t")
            return {"ok": True, "freq": int(f[0]), "mode": m[0], "passband": m[1] if len(m) > 1 else "",
                    "ptt": ptt[0] == "1"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def set_freq(self, hz):
        return self.cmd("F %d" % int(hz))

    def set_mode(self, mode, passband=0):
        r = self.cmd("M %s %d" % (mode, passband))
        if r and r[-1].startswith("RPRT") and r[-1] != "RPRT 0":
            raise RuntimeError("rig rejected mode %s (%s)" % (mode, r[-1]))
        return r

    def set_data_usb(self):
        """Select USB data mode, falling back to plain USB on rigs without PKTUSB."""
        try:
            self.set_mode("PKTUSB", 0)
        except RuntimeError:
            self.set_mode("USB", 0)

    def ptt(self, on):
        return self.cmd("T %d" % (1 if on else 0))
