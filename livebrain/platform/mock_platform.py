"""模拟平台适配器（M1）：弹幕脚本 + 判罚信号 + 运营动作执行。

- poll()：free_run 模式下每 tick 弹出最早的一条预定事件（确定性，测试/演示用）；
- push_speech()：模拟平台审核——话术含平台违禁词则回吐 judgment 事件
  （判罚信号接入感知层，R9）；
- ops()：运营动作 API（上链接/发券），承诺队列核销的执行端；
- registered：报备状态，未报备拒绝开播（合规门禁）。
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..decision.types import OpsAction
from ..events import LiveEvent, judgment_event
from ..execution.compliance import ComplianceProfile

DEFAULT_PROFILE = ComplianceProfile(
    platform="mock", label_text="AI虚拟主播", min_area_ratio=0.10,
    position="top-center", requires_registration=True)


@dataclass
class ActionResult:
    ok: bool
    detail: str = ""


class MockPlatform:
    def __init__(self, room_id: str,
                 compliance_profile: Optional[ComplianceProfile] = None,
                 banned_words: Tuple[str, ...] = ("库存告急",),
                 registered: bool = True,
                 ops_failure_rate: float = 0.0,
                 human_capture=None,
                 avatar_asset_id: Optional[str] = None) -> None:
        self.room_id = room_id
        self.compliance_profile = compliance_profile or DEFAULT_PROFILE
        self.banned_words = banned_words
        self.registered = registered
        self.ops_failure_rate = ops_failure_rate
        self.human_capture = human_capture          # 混播：真人采集通道（V4.2）
        self.avatar_asset_id = avatar_asset_id      # 形象资产（开播门禁校验用）
        self._schedule: List[Tuple[float, LiveEvent]] = []
        self._t0: Optional[float] = None
        self._ops_seq = 0
        self.ops_log: List[Dict[str, Any]] = []
        self.speech_log: List[Dict[str, Any]] = []

    # ---- 生命周期 ----
    def start(self, now: float) -> None:
        self._t0 = now

    def schedule(self, delay_s: float, event: LiveEvent) -> None:
        self._schedule.append((delay_s, event))

    def has_pending(self, now: float = None) -> bool:
        return bool(self._schedule)

    def poll(self, now: float) -> List[LiveEvent]:
        """free_run：每次弹出最早的一条预定事件（确定性时序）。"""
        if not self._schedule:
            return []
        self._schedule.sort(key=lambda item: item[0])
        _delay, event = self._schedule.pop(0)
        return [event]

    # ---- 推流通道 ----
    async def push_speech(self, utterance_id: str, text: str,
                          meta: Optional[Dict[str, Any]] = None) -> List[LiveEvent]:
        self.speech_log.append({
            "utterance_id": utterance_id, "text": text, "meta": meta or {}})
        hits = [w for w in self.banned_words if w in text]
        if not hits:
            return []
        # 模拟平台审核回吐判罚信号（限流级）
        return [judgment_event(self.room_id, 0.0, "warn",
                               "platform_banned_word:%s" % ",".join(hits))]

    # ---- 运营动作 API ----
    async def ops(self, action: OpsAction) -> ActionResult:
        self._ops_seq += 1
        fail = (self.ops_failure_rate >= 1.0
                or (self.ops_failure_rate > 0 and self._ops_seq % 2 == 0))
        entry = {"seq": self._ops_seq, **action.to_dict(), "ok": not fail}
        self.ops_log.append(entry)
        await asyncio.sleep(0)
        if fail:
            return ActionResult(False, "platform_rejected")
        return ActionResult(True, "done:%s#%d" % (action.action, self._ops_seq))
