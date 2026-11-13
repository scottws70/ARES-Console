"""Start and stop the helper programs Winlink needs (Hamlib rigctld and the ARDOP TNC).

Each helper is considered "running" when its TCP port answers, so it does not
matter whether ARES Console or the operator started it.  Output from helpers
started here goes to a log file in the data folder so start-up errors (wrong
serial port, sound card busy, ...) can be shown to the operator.
"""
import os
import shlex
import shutil
import socket
import subprocess
import threading
import time

ENV_NAME_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def split_command(text):
    """'VAR=x VAR2=y prog args' -> (env dict, argv).  Leading NAME=value words set the environment."""
    words = shlex.split(text or "", posix=True)
    env = {}
    while words and "=" in words[0] and not words[0].startswith("="):
        name, val = words[0].split("=", 1)
        if not name or set(name) - ENV_NAME_OK:
            break
        env[name] = val
        words.pop(0)
    return env, words


def port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host or "127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1", "")
_netstat_cache = [0.0, set()]


def _listening_ports():
    """TCP ports something on this computer is listening on, found without connecting
    (ARDOP accepts only one host connection, so a test connection would disturb it)."""
    ports = set()
    if os.path.isfile("/proc/net/tcp"):
        for name in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                with open(name) as fh:
                    next(fh)
                    for line in fh:
                        f = line.split()
                        if len(f) > 3 and f[3] == "0A":  # LISTEN
                            ports.add(int(f[1].rsplit(":", 1)[1], 16))
            except (OSError, ValueError, StopIteration):
                pass
        return ports
    if time.time() - _netstat_cache[0] < 1.5:
        return _netstat_cache[1]
    try:
        out = subprocess.run(["netstat", "-an", "-p", "TCP"] if os.name == "nt" else ["netstat", "-an"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=0x08000000 if os.name == "nt" else 0).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 4 and ("LISTEN" in line.upper()):
            addr = f[1] if os.name == "nt" else f[3]
            try:
                ports.add(int(addr.replace(".", ":").rsplit(":", 1)[1]))
            except (ValueError, IndexError):
                pass
    _netstat_cache[:] = [time.time(), ports]
    return ports


def is_listening(host, port, probe=False):
    """True if host:port has a listener.  Local ports are checked passively; a remote
    port is only checked with a test connection when probe=True (safe for rigctld)."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if (host or "") in LOCAL_HOSTS:
        ports = _listening_ports()
        if ports is not None:
            return port in ports
    return port_open(host, port) if probe else None


def rigctld_check(host, port, timeout=6.0):
    """Ask rigctld for the frequency.  Returns None if the radio answered, else the problem."""
    try:
        with socket.create_connection((host or "127.0.0.1", int(port)), timeout=timeout) as s:
            s.sendall(b"f\n")
            data = b""
            while b"\n" not in data:
                chunk = s.recv(256)
                if not chunk:
                    break
                data += chunk
    except socket.timeout:
        return "the radio did not answer"
    except OSError as e:
        return str(e)
    line = data.decode("ascii", "replace").strip().splitlines()[0] if data.strip() else ""
    if line.isdigit():
        return None
    return "rigctld replied %r" % line if line else "the radio did not answer"


def _windows_search(exe_name):
    """Common install locations on Windows for programs that are not on PATH."""
    roots = [os.environ.get("ProgramFiles", r"C:\Program Files"),
             os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("LOCALAPPDATA", "")]
    for root in filter(None, roots):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for d in names:
            low = d.lower()
            if low.startswith(("hamlib", "ardop")):
                for sub in ("bin", ""):
                    cand = os.path.join(root, d, sub, exe_name)
                    if os.path.isfile(cand):
                        return cand
    return None


class Helper:
    def __init__(self, key, title, data_dir):
        self.key = key
        self.title = title
        self.log_path = os.path.join(data_dir, key + ".log")
        self.proc = None
        self.lock = threading.Lock()

    def started_here(self):
        return self.proc is not None and self.proc.poll() is None

    def log_tail(self, n=6):
        try:
            with open(self.log_path, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 4000))
                lines = fh.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return ""
        return "\n".join(l for l in lines[-n:] if l.strip())

    def start(self, command, host, port, wait=8.0, probe=False, verify=None):
        """Start the helper and wait until its port listens.  Raises ValueError with the reason.
        verify(host, port) -> None or a problem string; on a problem the helper is stopped."""
        with self.lock:
            if is_listening(host, port, probe):
                return {"already_running": True}
            env_extra, argv = split_command(command)
            if not argv:
                raise ValueError("No command set for %s. Enter it in Settings." % self.title)
            exe = shutil.which(argv[0])
            if not exe and os.name == "nt":
                name = argv[0] if argv[0].lower().endswith(".exe") else argv[0] + ".exe"
                exe = _windows_search(os.path.basename(name))
            if not exe:
                raise ValueError("%s program not found (%s). Install it or put its full path in Settings."
                                 % (self.title, argv[0]))
            env = dict(os.environ)
            env.update(env_extra)
            log = open(self.log_path, "ab")
            log.write(("\n=== %s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), command)).encode())
            log.flush()
            kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT,
                  "env": env, "cwd": os.path.dirname(self.log_path)}
            if os.name == "nt":
                kw["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | NEW_PROCESS_GROUP
            else:
                kw["start_new_session"] = True
            try:
                self.proc = subprocess.Popen([exe] + argv[1:], **kw)
            finally:
                log.close()
            deadline = time.time() + wait
            while time.time() < deadline:
                if is_listening(host, port, probe):
                    problem = verify(host, port) if verify else None
                    if problem:
                        p, self.proc = self.proc, None
                        p.terminate()
                        try:
                            p.wait(3)
                        except subprocess.TimeoutExpired:
                            p.kill()
                        tail = self.log_tail()
                        raise ValueError("%s started, but %s, so it was stopped. Check the rig model, "
                                         "serial port and baud rate, that the radio is on, and that no "
                                         "other program (e.g. JS8Call) has the serial port open.%s"
                                         % (self.title, problem, ("\n" + tail) if tail else ""))
                    return {"already_running": False, "pid": self.proc.pid}
                if self.proc.poll() is not None:
                    tail = self.log_tail()
                    self.proc = None
                    raise ValueError("%s stopped right after starting.%s" % (
                        self.title, ("\n" + tail) if tail else ""))
                time.sleep(0.25)
            tail = self.log_tail()
            raise ValueError("%s started but is not answering on port %s yet.%s" % (
                self.title, port, ("\n" + tail) if tail else ""))

    def stop(self):
        with self.lock:
            p, self.proc = self.proc, None
        if p is None or p.poll() is not None:
            return False
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
        return True

    def status(self, host, port, probe=False):
        running = is_listening(host, port, probe)
        if running is None:  # remote and not probed: only know about our own process
            running = self.started_here()
        return {"running": running, "started_here": self.started_here(),
                "log": self.log_tail(3)}
