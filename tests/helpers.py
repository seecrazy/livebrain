"""测试共享工具：可控时钟。"""

import asyncio


class FakeClock:
    """now() 可手动推进；sleep 推进虚拟时间并让出事件循环（打断可测）。"""

    def __init__(self, start: float = 1000000.0) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        await asyncio.sleep(0)
