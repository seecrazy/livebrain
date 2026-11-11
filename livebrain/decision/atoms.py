"""话术原子与承诺队列（DESIGN §6.6）：AI 永不开空头支票。

- 话术原子 = 模板 + ops 副作用绑定（如 [atom:link_up] -> 上链接 API）；
- LLM/规则只能引用原子 ID，不能自由生成动作性承诺；
- 自由文本出现承诺词（保证/秒发/假一赔十…）且不来自原子模板 -> 拦截；
- 被播出的话术原子生成 Promise，由承诺队列调用平台 API 核销，超时告警人工。
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..util import uid
from .types import OpsAction

ATOM_REF = re.compile(r"\[atom:(\w+)\]")

# 自由文本禁用的承诺词（原子模板是策展内容，不受此限制）
PROMISE_WORDS = ["保证", "承诺", "秒发", "假一赔十", "假一赔百", "无效退款", "随时退"]


class UnboundPromiseError(Exception):
    """自由文本中出现未绑定原子的承诺词。"""

    def __init__(self, words: List[str]) -> None:
        self.words = words
        super().__init__("unbound promise words: %s" % words)


@dataclass
class UtteranceAtom:
    atom_id: str
    template: str
    ops_action: Optional[str] = None
    ops_params: Dict[str, Any] = field(default_factory=dict)


REGISTRY: Dict[str, UtteranceAtom] = {
    "link_up": UtteranceAtom(
        "link_up", "三、二、一，链接上了，宝宝们直接拍！", "link_up", {}),
    "coupon_5": UtteranceAtom(
        "coupon_5", "先领张五元优惠券再拍，更划算！", "coupon", {"amount": 5}),
    "welfare": UtteranceAtom(
        "welfare", "马上整一波福利，宝宝们扣个想要！", None, {}),
}


def expand(text: str) -> Tuple[str, List[OpsAction]]:
    """展开原子引用 -> (最终文本, 待执行 ops 列表)。

    先剥离原子引用扫描自由文本的承诺词，再展开模板。
    """
    remainder = ATOM_REF.sub("", text)
    bad = [w for w in PROMISE_WORDS if w in remainder]
    if bad:
        raise UnboundPromiseError(bad)

    ops: List[OpsAction] = []

    def _sub(match: "re.Match") -> str:
        atom = REGISTRY[match.group(1)]
        if atom.ops_action:
            ops.append(OpsAction(atom.ops_action, dict(atom.ops_params)))
        return atom.template

    return ATOM_REF.sub(_sub, text), ops


@dataclass
class Promise:
    promise_id: str
    utterance_id: str
    ops: OpsAction
    created_ts: float
    deadline_ts: float
    status: str = "pending"          # pending / fulfilled / expired
    failures: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "promise_id": self.promise_id,
            "utterance_id": self.utterance_id,
            "ops": self.ops.to_dict(),
            "status": self.status,
        }


class PromiseQueue:
    """承诺队列：核销（调平台 API）或超时告警。全部状态变化进审计。"""

    def __init__(self, clock, audit, deadline_s: float = 30.0,
                 room_id: str = "") -> None:
        self.clock = clock
        self.audit = audit
        self.deadline_s = deadline_s
        self.room_id = room_id
        self.promises: List[Promise] = []
        self.alerts: List[str] = []

    def submit(self, ops: OpsAction, utterance_id: str) -> Promise:
        now = self.clock.now()
        promise = Promise(
            promise_id=uid("prm"), utterance_id=utterance_id, ops=ops,
            created_ts=now, deadline_ts=now + self.deadline_s)
        self.promises.append(promise)
        self.audit.append("promise", self.room_id,
                          {"event": "created", **promise.to_dict()})
        return promise

    def pending(self) -> List[Promise]:
        return [p for p in self.promises if p.status == "pending"]

    def has_pending(self) -> bool:
        return bool(self.pending())

    async def execute_pending(self, adapter) -> None:
        now = self.clock.now()
        for promise in self.pending():
            if now > promise.deadline_ts:
                promise.status = "expired"
                self.alerts.append("promise_expired:%s" % promise.promise_id)
                self.audit.append("promise", self.room_id, {"event": "expired",
                                                            **promise.to_dict()})
                continue
            try:
                result = await adapter.ops(promise.ops)
            except Exception as exc:  # 平台 API 异常：保留待重试
                promise.failures += 1
                self.audit.append("promise", self.room_id, {
                    "event": "execute_error", "error": str(exc),
                    **promise.to_dict()})
                continue
            if result.ok:
                promise.status = "fulfilled"
                self.audit.append("promise", self.room_id, {"event": "fulfilled",
                                                            "detail": result.detail,
                                                            **promise.to_dict()})
            else:
                promise.failures += 1
                self.audit.append("promise", self.room_id, {
                    "event": "execute_rejected", "detail": result.detail,
                    **promise.to_dict()})
