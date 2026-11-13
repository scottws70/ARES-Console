"""Tiny pub/sub bus used to push live updates to browsers via Server-Sent Events."""
import queue
import threading


class Bus:
    def __init__(self):
        self.lock = threading.Lock()
        self.subs = set()

    def subscribe(self):
        q = queue.Queue(maxsize=1000)
        with self.lock:
            self.subs.add(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            self.subs.discard(q)

    def publish(self, kind, data=None):
        msg = {"type": kind, "data": data}
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


bus = Bus()
