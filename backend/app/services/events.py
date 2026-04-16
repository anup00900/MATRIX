import asyncio, itertools
from collections import defaultdict


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._seq = itertools.count(1)

    def subscribe(self, channel: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subs[channel].append(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue) -> None:
        if q in self._subs.get(channel, []):
            self._subs[channel].remove(q)

    async def publish(self, channel: str, payload: dict) -> None:
        payload = {"id": next(self._seq), **payload}
        for q in list(self._subs.get(channel, [])):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


bus = EventBus()
