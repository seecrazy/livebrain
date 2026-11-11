"""意图预分类：纯本地规则匹配，毫秒级。

路由约定（见 DESIGN §5.3 / §6.1）：
  price_stock     -> 快轨（规则引擎）
  product_consult -> 中轨（RAG+LLM+填槽）
  interact        -> 按场控阶段回复率决定
  sensitive       -> 固定模板，零生成
  action_request  -> 固定模板，零生成（承诺诱导）
  noise           -> 丢弃
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

# 意图常量（字符串，便于审计序列化）
PRICE_STOCK = "price_stock"
PRODUCT_CONSULT = "product_consult"
INTERACT = "interact"
SENSITIVE = "sensitive"
ACTION_REQUEST = "action_request"
SONG_REQUEST = "song_request"      # 点歌（V4.4 场景包）
JOKE_REQUEST = "joke_request"      # 段子/包袱（V4.4 场景包）
NOISE = "noise"

# 快轨子类型
SUB_PRICE = "price"
SUB_STOCK = "stock"
SUB_SHIP = "ship"
SUB_COUPON = "coupon"

_PRICE_WORDS = ["多少钱", "价格", "价位", "贵不贵", "便宜", "啥价", "卖多少", "几块"]
_STOCK_WORDS = ["有货吗", "没货", "库存", "还剩多少", "缺货", "补货"]
_SHIP_WORDS = ["发货", "物流", "几天到", "什么时候到", "顺丰", "包邮"]
_COUPON_WORDS = ["优惠", "券", "打折", "折扣", "满减", "活动价", "便宜点"]

_CONSULT_WORDS = [
    "适合", "敏感", "干皮", "油皮", "混合皮", "成分", "含量", "怎么用", "用法",
    "效果", "保质期", "规格", "多大", "区别", "对比", "哪个好", "好用吗",
    "孕妇", "哺乳", "小孩能用", "老人", "学生党", "新手",
    "晚间", "白天", "早晚", "美白", "抗老", "紧致", "祛痘", "祛斑",
    "过敏", "刺痛", "长痘", "闭口",
]

# 敏感意图：功效/医疗宣称诱导 —— 固定拒答模板，绝不走生成
_SENSITIVE_WORDS = [
    "治疗", "治好", "根治", "治病", "药效", "药用", "疗效", "抗癌", "防癌",
    "降血糖", "降血压", "降血脂", "消炎", "杀菌", "痊愈", "治病吗", "能治",
    "副作用", "替代药物", "停药",
]

# 承诺诱导：观众逼 AI 开空头支票 —— 固定模板，绝不走生成
_ACTION_WORDS = [
    "保证", "你承诺", "承诺", "无效退款", "假一赔十",
    "假一赔百", "秒发货", "秒发", "随时退", "吃了不好退",
]

# 购买意图（提升事件优先级 + 不受回复率预算限制）
_PURCHASE_WORDS = ["链接", "怎么拍", "怎么买", "如何拍", "下单", "拍了", "上链接", "去哪买", "怎样购买"]

# 点歌 / 段子（场景包意图，非对应场景由场景包礼貌婉拒）
_SONG_WORDS = ["唱一首", "来一首", "点歌", "点一首", "唱个歌", "安可", "想听你唱"]
_JOKE_WORDS = ["讲个段子", "来个段子", "说个段子", "讲个笑话", "说个笑话",
               "来个笑话", "来个包袱", "抖个包袱", "返场"]

# 互动闲聊
_INTERACT_WORDS = [
    "哈哈哈", "主播", "好看", "加油", "来了", "666", "支持", "爱了", "hello",
    "你好", "晚上好", "早上好", "大家好", "刚来", "第一", "签到", "真人吗",
    "是真人", "数字人", "机器人", "彩蛋", "音乐", "唱歌", "跳个舞",
    "再来一段", "继续", "经典", "节奏真好", "有意思", "笑死",
]

_EMOJI_ONLY = re.compile(r"^[\W\s_]+$")


@dataclass
class IntentResult:
    intent: str
    subtype: Optional[str] = None      # 快轨子类型 / 咨询主题词
    purchase_intent: bool = False
    topic_key: str = ""                # 聚合分组的主题键
    matched: List[str] = field(default_factory=list)


def _match_any(text: str, words: List[str]) -> List[str]:
    return [w for w in words if w in text]


def classify(text: str) -> IntentResult:
    """分类顺序：敏感 > 承诺诱导 > 快轨 > 咨询 > 互动 > 噪音。

    敏感/诱导优先级最高：哪怕句子里同时有价格词，也绝不能进生成路径。
    """
    if not text or _EMOJI_ONLY.match(text):
        return IntentResult(intent=NOISE, topic_key="noise")

    purchase = bool(_match_any(text, _PURCHASE_WORDS))

    if _match_any(text, _SENSITIVE_WORDS):
        return IntentResult(intent=SENSITIVE, purchase_intent=purchase,
                            topic_key="sensitive", matched=_match_any(text, _SENSITIVE_WORDS))

    if _match_any(text, _ACTION_WORDS):
        return IntentResult(intent=ACTION_REQUEST, purchase_intent=purchase,
                            topic_key="action", matched=_match_any(text, _ACTION_WORDS))

    if _match_any(text, _SONG_WORDS):
        return IntentResult(intent=SONG_REQUEST, purchase_intent=False,
                            topic_key="song", matched=_match_any(text, _SONG_WORDS))
    if _match_any(text, _JOKE_WORDS):
        return IntentResult(intent=JOKE_REQUEST, purchase_intent=False,
                            topic_key="joke", matched=_match_any(text, _JOKE_WORDS))

    price_hits = _match_any(text, _PRICE_WORDS)
    stock_hits = _match_any(text, _STOCK_WORDS)
    ship_hits = _match_any(text, _SHIP_WORDS)
    coupon_hits = _match_any(text, _COUPON_WORDS)
    if price_hits or stock_hits or ship_hits or coupon_hits:
        if stock_hits:
            subtype, matched = SUB_STOCK, stock_hits
        elif ship_hits:
            subtype, matched = SUB_SHIP, ship_hits
        elif coupon_hits:
            subtype, matched = SUB_COUPON, coupon_hits
        else:
            subtype, matched = SUB_PRICE, price_hits
        return IntentResult(intent=PRICE_STOCK, subtype=subtype,
                            purchase_intent=purchase,
                            topic_key="fast:" + subtype, matched=matched)

    consult_hits = _match_any(text, _CONSULT_WORDS)
    if consult_hits:
        topic = consult_hits[0]
        return IntentResult(intent=PRODUCT_CONSULT, subtype=topic,
                            purchase_intent=purchase,
                            topic_key="consult:" + topic, matched=consult_hits)

    # 购买意图但未命中其他意图（"怎么拍/有链接吗"）-> 归入快轨价格/上链接
    if purchase:
        return IntentResult(intent=PRICE_STOCK, subtype="price",
                            purchase_intent=True, topic_key="fast:buy",
                            matched=["purchase"])

    if _match_any(text, _INTERACT_WORDS):
        return IntentResult(intent=INTERACT, purchase_intent=purchase,
                            topic_key="interact")

    return IntentResult(intent=NOISE, topic_key="noise")
