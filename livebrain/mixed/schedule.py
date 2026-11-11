"""混播排班器（DESIGN §7.7）：时段表驱动 AI/真人切换。

排班语义：
- 段序列 [{"duration_s": 600, "mode": "ai", "label": "长尾品讲解"},
          {"duration_s": 1800, "mode": "human", "label": "主推品真人场"}, ...]
- 边界跨越时返回模式切换事件；同模相邻段不产生事件；
- 切回 AI 走 rehandoff 语义（未核销承诺会阻塞并告警，由运营 force 放行）。
时间基准：开播时刻（platform.start），clock.now() 真实墙钟。
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ScheduleSegment:
    duration_s: float
    mode: str                    # "ai" | "human"
    label: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleSegment":
        return cls(float(data.get("duration_s", 0)),
                   data.get("mode", "ai"), data.get("label", ""))


class MixedSchedule:
    def __init__(self, segments: Optional[List] = None) -> None:
        self.segments: List[ScheduleSegment] = [
            seg if isinstance(seg, ScheduleSegment) else ScheduleSegment.from_dict(seg)
            for seg in (segments or [])
        ]
        self._pos = 0
        self._start_ts: Optional[float] = None
        self._boundaries: List[float] = []       # 每段结束时刻（相对 start 累计）

    def begin(self, start_ts: float) -> None:
        self._start_ts = start_ts
        self._pos = 0
        acc = 0.0
        self._boundaries = []
        for seg in self.segments:
            acc += seg.duration_s
            self._boundaries.append(acc)

    def current_mode(self) -> str:
        if not self.segments:
            return "ai"
        return self.segments[min(self._pos, len(self.segments) - 1)].mode

    def elapsed(self, now: float) -> float:
        return 0.0 if self._start_ts is None else now - self._start_ts

    def pending(self, now: float) -> bool:
        """是否还有未到达的排班边界（编排器据此保持心跳）。"""
        return self._pos + 1 < len(self.segments)

    def poll(self, now: float) -> List[dict]:
        """推进到当前时刻，返回其间发生的模式切换事件（可能多条）。"""
        transitions: List[dict] = []
        while self._pos + 1 < len(self.segments):
            if self.elapsed(now) < self._boundaries[self._pos]:
                break
            old = self.segments[self._pos]
            self._pos += 1
            new = self.segments[self._pos]
            if new.mode != old.mode:
                transitions.append({
                    "to": new.mode,
                    "from": old.mode,
                    "label": new.label,
                    "boundary_s": self._boundaries[self._pos - 1],
                })
        return transitions
