"""事件总线：heapq 优先级队列，同优先级按序号先进先出。"""
import heapq
import itertools
from typing import List, Optional

from .events import LiveEvent


class PriorityEventQueue:
    def __init__(self) -> None:
        self._heap: List = []
        self._seq = itertools.count(1)

    def publish(self, event: LiveEvent) -> None:
        heapq.heappush(self._heap, (event.priority, next(self._seq), event))

    def get(self) -> Optional[LiveEvent]:
        if not self._heap:
            return None
        _, _, event = heapq.heappop(self._heap)
        return event

    def __len__(self) -> int:
        return len(self._heap)
