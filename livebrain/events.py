"""标准事件对象与总线优先级。

judgment(0) > control(1) > 高价值弹幕(3) > 普通弹幕(5) > 指标(8) > 进场/礼物(9)
"""
from dataclasses import dataclass, field
from typing import Any, Dict

# 事件种类
DANMU = "danmu"
GIFT = "gift"
ENTER = "enter"
METRIC = "metric"
OPS = "ops"
JUDGMENT = "judgment"
CONTROL = "control"

# 优先级（数值越小越优先）
PRIORITY_JUDGMENT = 0
PRIORITY_CONTROL = 1
PRIORITY_DANMU_HOT = 3
PRIORITY_DANMU = 5
PRIORITY_METRIC = 8
PRIORITY_ENTER = 9


@dataclass
class LiveEvent:
    kind: str
    room_id: str
    ts: float
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = PRIORITY_DANMU

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "room_id": self.room_id,
            "ts": self.ts,
            "priority": self.priority,
            "payload": self.payload,
        }


def danmu_event(room_id: str, user_id: str, text: str, ts: float,
                purchase_intent: bool = False) -> LiveEvent:
    return LiveEvent(
        kind=DANMU,
        room_id=room_id,
        ts=ts,
        priority=PRIORITY_DANMU_HOT if purchase_intent else PRIORITY_DANMU,
        payload={"user_id": user_id, "text": text},
    )


def metric_event(room_id: str, ts: float, online: int, stock_ratio: float) -> LiveEvent:
    return LiveEvent(
        kind=METRIC,
        room_id=room_id,
        ts=ts,
        priority=PRIORITY_METRIC,
        payload={"online": online, "stock_ratio": stock_ratio},
    )


def judgment_event(room_id: str, ts: float, level: str, reason: str) -> LiveEvent:
    return LiveEvent(
        kind=JUDGMENT,
        room_id=room_id,
        ts=ts,
        priority=PRIORITY_JUDGMENT,
        payload={"level": level, "reason": reason},
    )


def control_event(room_id: str, ts: float, action: str,
                  params: Dict[str, Any] = None) -> LiveEvent:
    return LiveEvent(
        kind=CONTROL,
        room_id=room_id,
        ts=ts,
        priority=PRIORITY_CONTROL,
        payload={"action": action, "params": params or {}},
    )
