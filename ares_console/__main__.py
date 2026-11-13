import argparse
import json
import os
import threading
import urllib.request
import webbrowser

from . import __version__
from .server import serve


def default_data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "ARES-Console")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "ares-console")


def already_running(port):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/version" % port, timeout=2) as r:
            return json.load(r).get("app") == "ARES Console"
    except Exception:  # noqa
        return False


def main():
    p = argparse.ArgumentParser(prog="ares-console", description="ARES Net Control Console")
    p.add_argument("--host", default="127.0.0.1", help="bind address (use 0.0.0.0 to allow other computers on the LAN)")
    p.add_argument("--port", type=int, default=8073)
    p.add_argument("--data", default=None, help="data directory (default: %s)" % default_data_dir())
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--version", action="version", version="ARES Console " + __version__)
    a = p.parse_args()
    url = "http://127.0.0.1:%d/" % a.port
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("ARES Console - close this window to stop")
        except Exception:  # noqa
            pass
    if already_running(a.port):
        # A second launch (e.g. from the menu) just opens the running console.
        print("ARES Console is already running at " + url)
        if not a.no_browser:
            webbrowser.open(url)
        return
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    serve(a.host, a.port, a.data or default_data_dir())


if __name__ == "__main__":
    main()
