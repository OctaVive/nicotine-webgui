import hmac
import secrets
import time
from collections import deque
from http.cookies import SimpleCookie, CookieError
from threading import RLock

from .errors import APIError


class Auth:
    def __init__(self, token, ttl=43200, limit=32):
        self.token, self.ttl, self.limit = token, ttl, limit
        self.sessions = {}
        self.attempts = deque()
        self.mutations = deque()
        self.lock = RLock()

    def rate(self, bucket, count, seconds):
        now = time.monotonic()
        with self.lock:
            while bucket and bucket[0] <= now - seconds:
                bucket.popleft()
            if len(bucket) >= count:
                raise APIError(429, "rate_limited", "Too many requests; retry later")
            bucket.append(now)

    def login(self, token):
        self.rate(self.attempts, 5, 60)
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
            raise APIError(401, "unauthenticated", "Invalid token")
        with self.lock:
            self._prune()
            if len(self.sessions) >= self.limit:
                raise APIError(503, "busy", "Session capacity reached")
            sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self.sessions[sid] = {"csrf": csrf, "expires": time.time() + self.ttl}
            return sid, self.sessions[sid].copy()

    def _prune(self):
        now = time.time()
        self.sessions = {k: v for k, v in self.sessions.items() if v["expires"] > now}

    def session(self, cookie):
        try:
            cookies = SimpleCookie()
            cookies.load(cookie or "")
            sid = cookies["npw_session"].value
        except (KeyError, CookieError):
            raise APIError(401, "unauthenticated", "Please log in") from None
        with self.lock:
            self._prune()
            session = self.sessions.get(sid)
            if session is None:
                raise APIError(401, "unauthenticated", "Session expired")
            return sid, session.copy()

    def check_csrf(self, session, csrf):
        if not hmac.compare_digest(session["csrf"].encode(), (csrf or "").encode()):
            raise APIError(403, "csrf", "Invalid CSRF token")
        self.rate(self.mutations, 60, 1)

    def logout(self, sid):
        with self.lock:
            self.sessions.pop(sid, None)
