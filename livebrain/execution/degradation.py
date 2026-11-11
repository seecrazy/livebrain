"""能力降级链与熔断器（DESIGN §7.5）。

每个能力域（llm/tts/renderer）一条 provider 优先级链：
- 单 provider 失败进熔断器计数，窗口内失败达阈值 -> 熔断打开；
- 熔断打开时链自动切到下一个可用 provider，切换写审计，支持回滚；
- 全链熔断由调用方走兜底（如 LLM 链 -> 兜底话术池）。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..config import Settings

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class ProviderError(Exception):
    pass


@dataclass
class CircuitBreaker:
    name: str
    threshold: int
    window_s: float
    cooldown_s: float
    clock: object = None
    failures: List[float] = field(default_factory=list)
    open_until: Optional[float] = None

    def record_failure(self) -> None:
        now = self.clock.now()
        self.failures = [t for t in self.failures
                         if now - t < self.window_s]
        self.failures.append(now)
        if len(self.failures) >= self.threshold:
            self.open_until = now + self.cooldown_s

    def record_success(self) -> None:
        self.failures = []
        self.open_until = None

    def allow(self) -> bool:
        if self.open_until is None:
            return True
        return self.clock.now() >= self.open_until   # 半开探测

    def state(self) -> str:
        if self.open_until is None:
            return CLOSED
        return OPEN if self.clock.now() < self.open_until else HALF_OPEN


class CapabilityChain:
    def __init__(self, name: str, providers: List, settings: Settings,
                 audit, clock, room_id: str = "") -> None:
        self.name = name
        self.providers = providers
        self.audit = audit
        self.clock = clock
        self.room_id = room_id
        self.breakers: Dict[str, CircuitBreaker] = {
            p.name: CircuitBreaker(
                "%s/%s" % (name, p.name), settings.breaker_threshold,
                settings.breaker_window_s, settings.breaker_cooldown_s, clock)
            for p in providers
        }
        self._index = 0
        self.switch_log: List[Dict] = []

    def current_name(self) -> str:
        return self.providers[self._index].name

    def acquire(self) -> Optional[object]:
        """返回当前可用 provider；全部熔断返回 None。"""
        n = len(self.providers)
        for offset in range(n):
            pos = (self._index + offset) % n
            provider = self.providers[pos]
            if self.breakers[provider.name].allow():
                return provider
        return None

    def report_success(self, provider) -> None:
        self.breakers[provider.name].record_success()

    def report_failure(self, provider) -> Optional[Dict]:
        """报告失败；若因此熔断打开则切链并审计。返回切换事件。"""
        breaker = self.breakers[provider.name]
        breaker.record_failure()
        if breaker.state() in (OPEN, HALF_OPEN) and breaker.allow() is False:
            switch = self._rotate_past(provider)
            if switch:
                self.switch_log.append(switch)
                self.audit.append("provider_switch", self.room_id, switch)
                return switch
        return None

    def _rotate_past(self, provider) -> Optional[Dict]:
        n = len(self.providers)
        for offset in range(1, n):
            pos = (self._index + offset) % n
            candidate = self.providers[pos]
            if self.breakers[candidate.name].allow():
                event = {
                    "chain": self.name,
                    "from": provider.name,
                    "to": candidate.name,
                    "reason": "breaker_open",
                    "ts": self.clock.now(),
                }
                self._index = pos
                return event
        return None

    def rollback(self) -> None:
        self._index = 0
        self.audit.append("provider_switch", self.room_id, {
            "chain": self.name, "to": self.providers[0].name,
            "reason": "manual_rollback", "ts": self.clock.now()})
