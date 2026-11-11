"""决策层共享类型：运营动作与话术任务。"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 话术轨道
TRACK_TEMPLATE = "template"      # 固定模板（敏感/诱导/升级保守应答），零生成
TRACK_FAST = "fast"              # 快轨：规则引擎
TRACK_MID = "mid"                # 中轨：RAG+LLM+填槽
TRACK_FALLBACK = "fallback"      # 兜底话术池（LLM 链熔断）

# 打断优先级：数值越小越优先。快轨(2)可打断中轨(4)。
PRIORITY_TEMPLATE = 1
PRIORITY_FAST = 2
PRIORITY_MID = 4
PRIORITY_INTERACT = 6
PRIORITY_FILLER = 7                   # 等待期衔接话术，最低优先级


@dataclass
class OpsAction:
    """运营动作：上链接/发券/改价。只能由话术原子绑定触发（防空头支票）。"""
    action: str                          # link_up / coupon / price_change
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"action": self.action, "params": self.params}


@dataclass
class SpeechTask:
    """一次待播报的话术任务。sentences 为最终填充完毕的文本。"""
    task_id: str
    track: str
    sentences: List[str]
    priority: int
    emotion: str = "steady"
    ops: List[OpsAction] = field(default_factory=list)
    origin: str = ""                     # 触发问题原文
    source: str = ""                     # rule_engine / mid_agent / template_sensitive / ...
    facts: Dict[str, str] = field(default_factory=dict)
    created_ts: float = 0.0
