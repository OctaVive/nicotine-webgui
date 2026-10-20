"""Bounded main-thread commands, with cancellation before execution."""
from concurrent.futures import Future, TimeoutError
from threading import RLock
from uuid import uuid4

from .errors import APIError


class Actions:
    def __init__(self, invoke, timeout=5, limit=256):
        self.invoke, self.timeout, self.limit = invoke, timeout, limit
        self.lock = RLock()
        self.commands = {}
        self.closed = False

    def execute(self, callback):
        with self.lock:
            if self.closed:
                raise APIError(503, "unavailable", "Bridge is stopping")
            if len(self.commands) >= self.limit:
                for key, future in list(self.commands.items()):
                    if future.done():
                        del self.commands[key]
                if len(self.commands) >= self.limit:
                    raise APIError(503, "busy", "Command queue is full")
            command_id, future = uuid4().hex, Future()
            self.commands[command_id] = future

        def run():
            if not future.set_running_or_notify_cancel():
                return
            try:
                future.set_result(callback())
            except Exception as error:
                future.set_exception(error)

        self.invoke(run)
        try:
            return 200, future.result(self.timeout)
        except TimeoutError:
            if future.cancel():
                raise APIError(503, "busy", "Command cancelled before execution; retry later") from None
            return 202, {"command_id": command_id, "state": "running"}

    def status(self, command_id):
        with self.lock:
            future = self.commands.get(command_id)
        if future is None:
            raise APIError(404, "not_found", "Command expired or unknown")
        if future.cancelled():
            return {"state": "cancelled"}
        if not future.done():
            return {"state": "running"}
        try:
            return {"state": "completed", "result": future.result()}
        except APIError as error:
            return {"state": "failed", "error": {"code": error.code, "message": error.message}}
        except Exception:
            return {"state": "failed", "error": {"code": "internal", "message": "Command failed"}}

    def close(self):
        with self.lock:
            self.closed = True
            for future in self.commands.values():
                future.cancel()
