"""人工接管与交回（DESIGN §7.6）。

- 热键接管：数字人音频淡出（请求打断）+ 真人接管，AI 静默；
- 交回：默认本场不自动交回；人工确认时若有未核销承诺必须 force，
  且返回状态摘要（人设/阶段/当前品/在线）供运营核对；
- 人工运营动作（发券/改价）同样进审计总线（R10）。
"""
from typing import Any, Dict, List, Optional, Tuple

from ..decision.atoms import PromiseQueue
from ..decision.persona import PersonaManager
from ..decision.types import OpsAction
from ..data.session import SessionState


class TakeoverController:
    def __init__(self, clock, audit, room_id: str = "") -> None:
        self.clock = clock
        self.audit = audit
        self.room_id = room_id
        self.mode = "ai"          # ai / human

    def ai_muted(self) -> bool:
        return self.mode == "human"

    def takeover(self, pipeline, reason: str = "manual") -> Dict[str, Any]:
        pipeline.request_interrupt()   # 当前话术音频淡出 + 视觉过渡
        self.mode = "human"
        payload = {"event": "takeover", "reason": reason}
        self.audit.append("takeover", self.room_id, payload)
        return payload

    def rehandoff(self, promises: PromiseQueue, persona: PersonaManager,
                  session: SessionState,
                  force: bool = False) -> Tuple[bool, Dict[str, Any]]:
        if self.mode != "human":
            return False, {"reason": "not_in_human_mode"}
        pending = promises.pending()
        if pending and not force:
            return False, {
                "reason": "pending_promises",
                "count": len(pending),
                "promise_ids": [p.promise_id for p in pending],
            }
        summary = {
            "persona": persona.current.persona_id,
            "stage": session.stage,
            "current_sku": session.current_sku,
            "online": session.online,
            "unfulfilled_promises": len(pending),
        }
        self.mode = "ai"
        self.audit.append("rehandoff", self.room_id,
                          {"event": "rehandoff", "summary": summary,
                           "forced": bool(pending)})
        return True, summary

    def human_ops(self, action: OpsAction,
                  result: Optional[Any] = None) -> None:
        self.audit.append("human_ops", self.room_id, {
            "action": action.to_dict(),
            "result": str(result) if result is not None else ""})
