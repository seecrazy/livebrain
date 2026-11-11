"""直播间数据加载（V4.3.1 / V4.4）：开播前装进编排器的一切内容。

通用块（电商与咨询）：
{
  "products": [{ "sku", "name", "category", "price"(元), "orig_price",
                 "stock", "total_stock", "ship_days", "coupons", "qual_flags" }],
  "knowledge": [{ "sku", "text", "keywords" }]
}

场景内容块（按 --format 生效，V4.4）：
{
  "chat":      { "topics": ["话题…"] },
  "music":     { "whitelist": ["已授权曲名…"] },        # 版权白名单=授权曲库
  "standup":   { "jokes": [{ "id", "setup", "punch" }] },
  "crosstalk": { "script": [{ "role": "A", "line": "…" }] }   # A=逗哏 B=捧哏
}
示例见 config/room.example.json。校验失败抛 ValueError（开播前发现）。
"""
import json
from typing import Any, Dict, Tuple

from ..data.product_store import CouponRule, Product
from ..decision.knowledge_store import KnowledgeDoc


def load_room_data(brain, path: str) -> Tuple[int, int]:
    """加载直播间数据：返回 (商品数, 知识条数)。首个商品自动设为当前讲品。

    场景内容块只在 brain.format 对应场景时装载（如 music.whitelist 只在
    --format music 时生效）。校验失败抛 ValueError（开播前发现，好过直播中翻车）。
    """
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError("直播间数据 JSON 解析失败：%s" % exc)

    products = data.get("products", [])
    if not isinstance(products, list):
        raise ValueError("products 必须是数组")
    for index, item in enumerate(products):
        _require(item, ("sku", "name", "price"), "products[%d]" % index)
        if float(item["price"]) <= 0:
            raise ValueError("products[%d].price 必须大于 0" % index)
        coupons = [
            CouponRule(rule.get("type", "full_cut"),
                       _yuan_to_cents(rule.get("threshold", 0)),
                       _yuan_to_cents(rule.get("cut", 0)))
            for rule in item.get("coupons", [])
            if float(rule.get("cut", 0)) > 0
        ]
        brain.store.upsert(Product(
            sku=str(item["sku"]),
            name=str(item["name"]),
            category=str(item.get("category", "beauty")),
            price=_yuan_to_cents(item["price"]),
            orig_price=_yuan_to_cents(item.get("orig_price", item["price"])),
            stock=int(item.get("stock", 0)),
            total_stock=int(item.get("total_stock", max(1, int(item.get("stock", 1))))),
            ship_days=int(item.get("ship_days", 2)),
            coupons=coupons,
            qual_flags=[str(f) for f in item.get("qual_flags", [])],
            updated_at=brain.clock.now()))

    knowledge = data.get("knowledge", [])
    if not isinstance(knowledge, list):
        raise ValueError("knowledge 必须是数组")
    for index, item in enumerate(knowledge):
        _require(item, ("text",), "knowledge[%d]" % index)
        brain.knowledge.add(KnowledgeDoc(
            doc_id="kd-custom-%d" % index,
            sku=str(item.get("sku", "")),
            text=str(item["text"]),
            keywords=[str(k) for k in item.get("keywords", [])]))

    if products:
        brain.session.current_sku = str(products[0]["sku"])

    _load_format_content(brain, data)
    return len(products), len(knowledge)


def _load_format_content(brain, data: Dict) -> None:
    """场景内容块装载：只对当前场景生效。"""
    fmt = brain.format
    block = data.get(fmt.format_id)
    if not isinstance(block, dict):
        return

    if fmt.format_id == "chat":
        topics = [str(t) for t in block.get("topics", []) if str(t).strip()]
        if topics:
            fmt.topics = topics
    elif fmt.format_id == "music":
        whitelist = [str(s) for s in block.get("whitelist", [])
                     if str(s).strip()]
        if whitelist:
            fmt.whitelist = whitelist          # 授权曲库整体替换
    elif fmt.format_id == "standup":
        jokes = []
        for index, joke in enumerate(block.get("jokes", [])):
            _require(joke, ("setup", "punch"), "standup.jokes[%d]" % index)
            jokes.append({
                "id": str(joke.get("id", "custom-%d" % index)),
                "setup": str(joke["setup"]), "punch": str(joke["punch"])})
        if jokes:
            fmt.jokes = jokes
    elif fmt.format_id == "crosstalk":
        script = []
        for index, beat in enumerate(block.get("script", [])):
            _require(beat, ("role", "line"), "crosstalk.script[%d]" % index)
            role = str(beat["role"]).upper()
            if role not in ("A", "B"):
                raise ValueError("crosstalk.script[%d].role 必须是 A(逗哏)/B(捧哏)"
                                 % index)
            script.append({"role": role, "line": str(beat["line"])})
        if script:
            fmt.script = script


def _yuan_to_cents(value: Any) -> int:
    return int(round(float(value) * 100))


def _require(item: Dict, keys: Tuple[str, ...], where: str) -> None:
    for key in keys:
        if key not in item:
            raise ValueError("%s 缺少必填字段 %s" % (where, key))
