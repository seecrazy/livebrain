"""填槽制（DESIGN §6.3）：LLM 全程不接触真实数字。

1. LLM 输出中数字信息只能是占位符 {price} {stock} {coupon} {ship_days} {online} {product_name}；
2. validate_generated 校验：未知占位符 / 自由文本裸数字 -> 拒绝（重试 1 次后落保守模板）；
3. fill 用规则引擎 facts 填充；出稿前必须全部填充完毕。
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

SLOT_RE = re.compile(r"\{([a-z_0-9]+)\}")
_DIGIT_RE = re.compile(r"[0-9０-９]")

KNOWN_SLOTS = {
    "price", "orig_price", "coupon", "stock", "ship_days", "online",
    "product_name", "final_price",
}


@dataclass
class SlotValidation:
    ok: bool
    problems: List[str] = field(default_factory=list)


def extract_slots(text: str) -> List[str]:
    return SLOT_RE.findall(text)


def validate_generated(text: str) -> SlotValidation:
    """校验 LLM 原始输出：占位符合法、无裸数字。"""
    problems: List[str] = []
    for slot in extract_slots(text):
        if slot not in KNOWN_SLOTS:
            problems.append("unknown_slot:" + slot)
    without_slots = SLOT_RE.sub("", text)
    if _DIGIT_RE.search(without_slots):
        problems.append("raw_digits")
    return SlotValidation(ok=not problems, problems=problems)


def fill(text: str, facts: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    """填充占位符。返回 (成品, 未填充列表)；未填充则成品为 None。"""
    unfilled: List[str] = []
    for slot in extract_slots(text):
        if slot not in facts:
            unfilled.append(slot)
    if unfilled:
        return None, unfilled

    def _sub(match: "re.Match") -> str:
        return facts[match.group(1)]

    return SLOT_RE.sub(_sub, text), []


def assert_no_raw_digits(text: str) -> bool:
    """出稿校验器最后一道：填充后的成品不得再含占位符或裸数字占位残留。"""
    return not extract_slots(text)
