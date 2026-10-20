"""Atomic mirror snapshots and replay; never retains live core objects."""
from collections import deque
from copy import deepcopy
from queue import Queue, Empty, Full
from threading import RLock
from uuid import uuid4

from .errors import APIError


class Store:
    def __init__(self, replay_limit=1000, client_limit=16, queue_limit=128):
        self.lock = RLock()
        self.instance = uuid4().hex
        self.revision = 0
        self.state = {}
        self.resource_revisions = {}
        self.ring = deque(maxlen=replay_limit)
        self.clients = set()
        self.client_limit, self.queue_limit = client_limit, queue_limit
        self.dropped = 0
        self.closed = False

    def cursor(self):
        return f"{self.instance}:{self.revision}"

    def snapshot(self, key=None):
        with self.lock:
            return {"ok": True, "data": deepcopy(self.state if key is None else self.state.get(key)),
                    "revision": self.revision, "resource_revision": self.resource_revisions.get(key, 0),
                    "instance": self.instance, "cursor": self.cursor()}

    def put(self, key, value, event=None):
        with self.lock:
            if self.state.get(key) == value:
                return
            self.state[key] = deepcopy(value)
            self.publish(event or key + ".updated", {"resource": key})
            self.resource_revisions[key] = self.revision

    def publish(self, name, data):
        with self.lock:
            self.revision += 1
            frame = {"id": self.cursor(), "event": name, "data": deepcopy(data)}
            self.ring.append(frame)
            for client in self.clients:
                try:
                    client.put_nowait(frame)
                except Full:
                    self.dropped += 1
                    while True:
                        try:
                            client.get_nowait()
                        except Empty:
                            break
                    client.put_nowait({"id": self.cursor(), "event": "resync", "data": {}})

    def subscribe(self, cursor=None):
        with self.lock:
            if self.closed or len(self.clients) >= self.client_limit:
                raise APIError(503, "busy", "Event stream capacity reached")
            queue = Queue(self.queue_limit)
            replay = []
            try:
                instance, revision = cursor.rsplit(":", 1)
                revision = int(revision)
                oldest = int(self.ring[0]["id"].rsplit(":", 1)[1]) if self.ring else self.revision + 1
                if instance != self.instance or revision < oldest - 1 or revision > self.revision:
                    raise ValueError()
                replay = [f for f in self.ring if int(f["id"].rsplit(":", 1)[1]) > revision]
            except (AttributeError, ValueError):
                replay = [{"id": self.cursor(), "event": "resync", "data": {}}]
            self.clients.add(queue)
            return queue, replay

    def unsubscribe(self, queue):
        with self.lock:
            self.clients.discard(queue)

    def forget(self, key):
        with self.lock:
            self.state.pop(key, None)
            self.resource_revisions.pop(key, None)

    def close(self):
        with self.lock:
            self.closed = True
            for queue in self.clients:
                try:
                    queue.put_nowait(None)
                except Full:
                    try:
                        queue.get_nowait()
                    except Empty:
                        pass
                    queue.put_nowait(None)
