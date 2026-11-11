"""弹幕消毒器：注入防护第一道防线。

弹幕是公开的对抗性输入，按不可信数据对待：
1. 控制字符剥离 + 长度截断；
2. 注入模式匹配 -> 隔离（quarantine），事件永不进入 LLM；
3. 隔离记录由编排器写入审计总线。
"""
import re
from dataclasses import dataclass, field
from typing import List

# 注入/越狱模式（中英）
_INJECTION_PATTERNS = [
    re.compile(r"忽略.{0,8}(之前|上面|以上|前面|刚才).{0,8}(指令|提示|设定|规则|要求)", re.I),
    re.compile(r"不理(会|睬).{0,10}(指令|规则|设定)", re.I),
    re.compile(r"ignore.{0,12}(all|any|previous|prior|above|earlier)", re.I),
    re.compile(r"disregard.{0,12}(all|any|previous|prior|above|instructions)", re.I),
    re.compile(r"(system|assistant|developer|系统|开发者|管理员)\s*[:：>】]", re.I),
    re.compile(r"你(现在|马上)?(是|变成|扮演|假扮|充当).{0,10}(另一个|别的|系统|开发者|管理员|客服|官方)", re.I),
    re.compile(r"(进入|开启|打开).{0,6}(开发者|管理员|越狱|jailbreak|dan).{0,6}(模式|mode)?", re.I),
    re.compile(r"jailbreak|developer\s*mode|dan\s*mode", re.I),
    re.compile(r"\{\{.*\}\}|<\|.*\|>|<script.*>|```", re.I | re.S),
    re.compile(r"(输出|打印|重复|告诉我).{0,8}(你的)?(系统提示|prompt|指令|设定)", re.I),
]

# 控制字符与零宽字符
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u202a-\u202e]")


@dataclass
class SanitizeResult:
    cleaned: str
    quarantined: bool = False
    reasons: List[str] = field(default_factory=list)


def sanitize(text: str, max_len: int = 120) -> SanitizeResult:
    """消毒一条弹幕。quarantined=True 表示必须隔离，不得进入生成路径。"""
    if not text:
        return SanitizeResult(cleaned="", quarantined=True, reasons=["empty"])

    cleaned = _CONTROL_CHARS.sub("", text).strip()
    reasons: List[str] = []

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(cleaned):
            reasons.append("injection:" + pattern.pattern[:40])

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]

    return SanitizeResult(cleaned=cleaned, quarantined=bool(reasons), reasons=reasons)
