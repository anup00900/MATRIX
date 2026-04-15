import asyncio, time

class TokenBudget:
    def __init__(self, tokens_per_minute: int, burst: int | None = None):
        self.rate = tokens_per_minute / 60.0
        self.capacity = burst or tokens_per_minute
        self._tokens = float(self.capacity)
        self._ts = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._ts) * self.rate)
                self._ts = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                deficit = n - self._tokens
                wait = deficit / self.rate
            await asyncio.sleep(wait)
