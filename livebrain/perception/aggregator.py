"""滑动窗口聚合 + 回复率预算。

弹幕洪峰不可能也不应该逐条回应：
- 同 topic（意图+子类型/主题词）在窗口内合并，一次回答覆盖多人；
- 回复率预算：滑动 60s 窗口内快轨/LLM 轨各有次数上限，超限静默丢弃；
- 购买意图与 sensitive/action 不受预算限制。
"""
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config import Settings


@dataclass
class AggregatedQuestion:
    intent: str
    subtype: Optional[str]
    topic_key: str
    representative_text: str
    count: int
    user_ids: List[str] = field(default_factory=list)
    purchase_intent: bool = False
    first_ts: float = 0.0

    @property
    def is_multi(self) -> bool:
        return self.count >= 2


class ReplyBudget:
    """滑动 60s 窗口的每轨回复次数预算。"""

    def __init__(self, fast_per_min: int, llm_per_min: int) -> None:
        self.limits = {"fast": fast_per_min, "llm": llm_per_min}
        self._history: Dict[str, List[float]] = {"fast": [], "llm": []}

    def allow(self, track: str, now: float) -> bool:
        hist = self._history[track]
        hist[:] = [t for t in hist if now - t < 60.0]
        return len(hist) < self.limits[track]

    def consume(self, track: str, now: float) -> None:
        self._history[track].append(now)


class QuestionAggregator:
    """窗口内同 topic 合并。

    语义：
    - price/敏感/诱导类：立即返回当前聚合（快轨不等待，后续同题并入下一答）；
    - 咨询类：等待窗口内凑对（count>=2）或窗口到期由 flush_due() 放行，
      避免为单条闲问付出 LLM 成本。
    """

    def __init__(self, settings: Settings, clock) -> None:
        self.settings = settings
        self.clock = clock
        self._open: Dict[str, AggregatedQuestion] = {}

    def add(self, intent: str, subtype: Optional[str], topic_key: str,
            text: str, user_id: str, purchase_intent: bool) -> Optional[AggregatedQuestion]:
        now = self.clock.now()
        q = self._open.get(topic_key)
        if q is None:
            q = AggregatedQuestion(
                intent=intent, subtype=subtype, topic_key=topic_key,
                representative_text=text, count=0, purchase_intent=purchase_intent,
                first_ts=now)
            self._open[topic_key] = q
        q.count += 1
        if user_id not in q.user_ids:
            q.user_ids.append(user_id)
        q.purchase_intent = q.purchase_intent or purchase_intent
        # 聚合后代表性文本保留更完整的一条，便于检索
        if len(text) > len(q.representative_text):
            q.representative_text = text

        if intent in ("price_stock", "sensitive", "action_request"):
            self._open.pop(topic_key, None)
            return q
        if q.count >= 2:
            self._open.pop(topic_key, None)
            return q
        return None

    def flush_due(self) -> List[AggregatedQuestion]:
        """窗口到期的咨询类问题放行。由编排器每个 tick 调用。"""
        now = self.clock.now()
        due = [q for q in self._open.values()
               if now - q.first_ts >= self.settings.aggregate_window_s]
        for q in due:
            self._open.pop(q.topic_key, None)
        return due

    def pending(self) -> List[AggregatedQuestion]:
        return list(self._open.values())
