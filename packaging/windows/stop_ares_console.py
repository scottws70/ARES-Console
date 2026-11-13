"""Ask a running ARES Console to shut down (used by the Windows uninstaller)."""
import urllib.request

try:
    urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8073/api/shutdown", data=b"{}",
                                                  method="POST"), timeout=3)
except Exception:  # not running
    pass
