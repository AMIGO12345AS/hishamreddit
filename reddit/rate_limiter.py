import time

class RedditRateLimiter:
    def __init__(self, per_minute: int = 60):
        self.per_minute = max(1, per_minute)
        self.interval = 60.0 / self.per_minute
        self._last = 0.0

    def wait(self):
        now = time.time()
        elapsed = now - self._last
        to_wait = self.interval - elapsed
        if to_wait > 0:
            time.sleep(to_wait)
        self._last = time.time()
