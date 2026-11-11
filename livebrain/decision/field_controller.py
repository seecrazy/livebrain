"""场控调度器（DESIGN §6.8）：阶段状态机，带滞回。

暖场期 WARMUP -> 讲解期 EXPLAIN -> 逼单期 CLOSING / 低谷期 VALLEY
切换条件需连续 hysteresis_ticks 个周期满足，防指标抖动来回切。
人设自动切换只允许发生在阶段边界（由编排器在 stage_change 时处理）。
"""
from dataclasses import dataclass
from typing import Optional, Tuple

from ..config import Settings

WARMUP = "warmup"
EXPLAIN = "explain"
CLOSING = "closing"
VALLEY = "valley"


@dataclass
class StageStrategy:
    name: str
    interact_reply_ratio: float    # 互动弹幕回复率
    price_priority_boost: int      # 价格问题优先级提升（打断能力）
    emotion: str


STRATEGIES = {
    WARMUP: StageStrategy(WARMUP, 1.0, 0, "cheerful"),
    EXPLAIN: StageStrategy(EXPLAIN, 0.2, 0, "steady"),
    CLOSING: StageStrategy(CLOSING, 0.3, 2, "urgent"),
    VALLEY: StageStrategy(VALLEY, 0.8, 0, "playful"),
}


class FieldController:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.stage = WARMUP
        self.peak_online = 0
        self._pending_target: Optional[str] = None
        self._ticks = 0

    def strategy(self) -> StageStrategy:
        return STRATEGIES[self.stage]

    def _wanted(self, online: int, stock_ratio: float) -> Tuple[str, str]:
        s = self.settings
        if self.stage == WARMUP:
            if online >= s.warmup_online:
                return EXPLAIN, "online>=warmup_threshold"
            return WARMUP, ""
        if self.stage == EXPLAIN:
            if stock_ratio < s.low_stock_ratio:
                return CLOSING, "stock_below_%.0f%%" % (s.low_stock_ratio * 100)
            if self.peak_online > 0 and online < self.peak_online * (1 - s.valley_drop_ratio):
                return VALLEY, "online_drop_over_%.0f%%" % (s.valley_drop_ratio * 100)
            return EXPLAIN, ""
        if self.stage == CLOSING:
            if stock_ratio > 0.5:
                return EXPLAIN, "stock_recovered"
            return CLOSING, ""
        # VALLEY
        if self.peak_online > 0 and online > self.peak_online * 0.7:
            return EXPLAIN, "online_recovered"
        return VALLEY, ""

    def update(self, online: int, stock_ratio: float) -> Optional[Tuple[str, str, str]]:
        """输入一个指标周期，返回 (旧阶段, 新阶段, 原因) 或 None。"""
        if online > self.peak_online:
            self.peak_online = online
        want, reason = self._wanted(online, stock_ratio)
        if want == self.stage:
            self._pending_target = None
            self._ticks = 0
            return None
        if want != self._pending_target:
            self._pending_target = want
            self._ticks = 1
        else:
            self._ticks += 1
        if self._ticks >= self.settings.hysteresis_ticks:
            old = self.stage
            self.stage = want
            self._ticks = 0
            self._pending_target = None
            if old == VALLEY and want == EXPLAIN:
                self.peak_online = online    # 低谷恢复后重置峰值基准
            return old, want, reason
        return None
