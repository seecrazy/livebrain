"""三道过滤 + 品类宣称引擎（DESIGN §6.5）。

1. 绝对违禁词（平台+商家黑名单）；
2. 广告法极限词；
3. 品类宣称规则：普通食品禁功效宣称；保健品类目须资质旗标（蓝帽子）才允许对应宣称；
   美妆禁医疗级表述。规则由商品库品类字段驱动。
"""
from dataclasses import dataclass, field
from typing import List

ABSOLUTE_BANNED = [
    "加微信", "私下转账", "线下交易", "刷单", "代购逃税", "货到付款私聊",
]

EXTREME_WORDS = [
    "最好", "最强", "最有效", "最低价", "全网最低", "史上最", "国家级",
    "顶级", "第一品牌", "销量冠军", "绝无仅有", "万能", "百分百有效",
    "无效退款", "根治", "包治",
]

# 品类宣称规则：forbidden 一律禁止；qualified 需要对应资质旗标
CATEGORY_CLAIMS = {
    "food": {
        "forbidden": ["治疗", "治好", "根治", "抗癌", "防癌", "降血糖", "降血压",
                      "降血脂", "消炎", "杀菌", "药效", "疗效", "痊愈", "停药",
                      "增强免疫"],
        "qualified": {},
    },
    "beauty": {
        "forbidden": ["医疗级", "药用", "治疗", "根治", "消炎", "杀菌",
                      "修复受损细胞", "抗炎"],
        "qualified": {},
    },
    "supplement": {
        "forbidden": ["根治", "包治", "替代药物"],
        "qualified": {"降血糖": "blue_hat", "降血压": "blue_hat",
                      "增强免疫": "blue_hat", "改善睡眠": "blue_hat"},
    },
}

DEFAULT_CLAIMS = {"forbidden": [], "qualified": {}}


@dataclass
class FilterResult:
    passed: bool
    blocked: List[str] = field(default_factory=list)

    @property
    def reason(self) -> str:
        return ";".join(self.blocked)


def check_claims(text: str, category: str, qual_flags: List[str]) -> List[str]:
    """品类宣称检查，返回命中的违规项描述。"""
    rules = CATEGORY_CLAIMS.get(category, DEFAULT_CLAIMS)
    hits: List[str] = []
    for word in rules["forbidden"]:
        if word in text:
            hits.append("category_forbidden:%s" % word)
    for word, flag in rules.get("qualified", {}).items():
        if word in text and flag not in qual_flags:
            hits.append("needs_qual:%s(%s)" % (word, flag))
    return hits


def check(text: str, category: str = "", qual_flags: List[str] = None) -> FilterResult:
    """对最终出稿文本做三道过滤。任何一道命中即拦截。"""
    qual_flags = qual_flags or []
    blocked: List[str] = []
    for word in ABSOLUTE_BANNED:
        if word in text:
            blocked.append("banned:%s" % word)
    for word in EXTREME_WORDS:
        if word in text:
            blocked.append("extreme:%s" % word)
    if category:
        blocked.extend(check_claims(text, category, qual_flags))
    return FilterResult(passed=not blocked, blocked=blocked)
