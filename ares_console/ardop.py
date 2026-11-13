"""ARDOP TNC host interface (ardopc / ardopcf) over TCP.

Command port (default 8515): CR-terminated ASCII commands/responses.
Data port (command port + 1): frames of 2-byte big-endian length + payload.
Inbound data payload starts with a 3-char tag ("ARQ", "FEC", "IDF", "ERR").
"""
import socket
import threading
import time


class ArdopError(Exception):
    pass


class Ardop:
    def __init__(self, host, port, mycall, grid="", bw="2000MAX", ptt_cb=None, log=None):
        self.host, self.port = host, int(port)
        self.mycall, self.grid, self.bw = mycall, grid, bw
        self.ptt_cb = ptt_cb
        self.log = log or (lambda s: None)
        self.cmd_sock = None
        self.data_sock = None
        self.rx = bytearray()
        self.rx_cv = threading.Condition()
        self.state = "DISC"
        self.connected = False
        self.closed = False
        self.buffer = 0
        self.events = []
        self.ev_cv = threading.Condition()

    # --- setup
    def open(self):
        self.cmd_sock = socket.create_connection((self.host, self.port), timeout=5)
        self.data_sock = socket.create_connection((self.host, self.port + 1), timeout=5)
        self.cmd_sock.settimeout(None)
        self.data_sock.settimeout(None)
        threading.Thread(target=self._cmd_reader, daemon=True).start()
        threading.Thread(target=self._data_reader, daemon=True).start()
        self.command("INITIALIZE")
        self.command("MYCALL %s" % self.mycall)
        if self.grid:
            self.command("GRIDSQUARE %s" % self.grid)
        self.command("PROTOCOLMODE ARQ")
        self.command("ARQBW %s" % self.bw)
        self.command("ARQTIMEOUT 120")
        self.command("LISTEN FALSE")

    def command(self, c):
        self.log("ARDOP> " + c)
        self.cmd_sock.sendall((c + "\r").encode())

    def _event(self, line):
        with self.ev_cv:
            self.events.append(line)
            self.ev_cv.notify_all()

    def _cmd_reader(self):
        buf = b""
        try:
            while True:
                d = self.cmd_sock.recv(1024)
                if not d:
                    break
                buf += d
                while b"\r" in buf:
                    line, buf = buf.split(b"\r", 1)
                    line = line.decode(errors="replace").strip()
                    if not line:
                        continue
                    self._handle_cmd(line)
        except OSError:
            pass
        self.closed = True
        with self.rx_cv:
            self.rx_cv.notify_all()
        self._event("CLOSED")

    def _handle_cmd(self, line):
        up = line.upper()
        if up.startswith("PTT "):
            on = up.endswith("TRUE")
            if self.ptt_cb:
                try:
                    self.ptt_cb(on)
                except Exception as e:  # noqa
                    self.log("PTT error: %s" % e)
            return
        if up.startswith("BUFFER"):
            try:
                self.buffer = int(up.split()[1])
            except (IndexError, ValueError):
                pass
            self._event(line)
            return
        self.log("ARDOP< " + line)
        if up.startswith("NEWSTATE"):
            self.state = up.split(" ", 1)[1] if " " in up else up
        if up.startswith("CONNECTED"):
            self.connected = True
        if up.startswith("DISCONNECTED"):
            self.connected = False
            with self.rx_cv:
                self.rx_cv.notify_all()
        self._event(line)

    def _recv_exact(self, n):
        out = b""
        while len(out) < n:
            d = self.data_sock.recv(n - len(out))
            if not d:
                raise ConnectionError("data port closed")
            out += d
        return out

    def _data_reader(self):
        try:
            while True:
                n = int.from_bytes(self._recv_exact(2), "big")
                payload = self._recv_exact(n)
                tag, data = payload[:3], payload[3:]
                if tag == b"ARQ":
                    with self.rx_cv:
                        self.rx += data
                        self.rx_cv.notify_all()
                elif tag in (b"FEC", b"IDF", b"ERR"):
                    self.log("ARDOP %s: %r" % (tag.decode(), data[:80]))
        except (OSError, ConnectionError):
            pass
        self.closed = True
        with self.rx_cv:
            self.rx_cv.notify_all()

    def wait_event(self, prefixes, timeout):
        deadline = time.time() + timeout
        with self.ev_cv:
            while True:
                for i, e in enumerate(self.events):
                    if any(e.upper().startswith(p) for p in prefixes):
                        del self.events[:i + 1]
                        return e
                rem = deadline - time.time()
                if rem <= 0:
                    return None
                self.ev_cv.wait(rem)

    # --- ARQ
    def connect(self, target, repeats=10, timeout=150, abort_check=None):
        with self.ev_cv:
            self.events.clear()
        self.command("ARQCALL %s %d" % (target, repeats))
        deadline = time.time() + timeout
        while time.time() < deadline:
            if abort_check and abort_check():
                self.command("ABORT")
                raise ArdopError("aborted")
            e = self.wait_event(["CONNECTED", "DISCONNECTED", "FAULT", "REJECTED", "CLOSED"], 1)
            if e is None:
                continue
            u = e.upper()
            if u.startswith("CONNECTED"):
                return e
            raise ArdopError("connect failed: " + e)
        self.command("ABORT")
        raise ArdopError("connect timed out")

    # transport API used by B2FSession
    def read(self, n, timeout):
        with self.rx_cv:
            if not self.rx:
                if self.closed or (not self.connected and self.state.startswith("DISC")):
                    return None
                self.rx_cv.wait(timeout)
            if not self.rx:
                if self.closed or not self.connected:
                    return None
                return b""
            out = bytes(self.rx[:n])
            del self.rx[:n]
            return out

    def write(self, data):
        for i in range(0, len(data), 2000):
            chunk = data[i:i + 2000]
            self.data_sock.sendall(len(chunk).to_bytes(2, "big") + chunk)

    def flush(self, timeout=600):
        """Wait until the TNC's outbound buffer has drained."""
        deadline = time.time() + timeout
        time.sleep(1.5)
        while time.time() < deadline and self.connected:
            self.command("BUFFER")
            self.wait_event(["BUFFER"], 3)
            if self.buffer == 0:
                return True
            time.sleep(1)
        return False

    def disconnect(self):
        try:
            if self.connected:
                self.flush(120)
                self.command("DISCONNECT")
                self.wait_event(["DISCONNECTED", "NEWSTATE DISC"], 30)
        except OSError:
            pass

    def abort(self):
        try:
            self.command("ABORT")
        except OSError:
            pass

    def close(self):
        for s in (self.cmd_sock, self.data_sock):
            try:
                if s:
                    s.close()
            except OSError:
                pass
