"""直播间数据加载（V4.3.1）：开播前把商家的商品库与知识库装进编排器。

JSON 格式（价格单位=元，内部自动转分）：
{
  "products": [{
      "sku": "SKU001", "name": "烟酰胺焕亮精华", "category": "beauty",
      "price": 129.0, "orig_price": 159.0,
      "stock": 30, "total_stock": 50, "ship_days": 2,
      "coupons": [{"type": "full_cut", "threshold": 100, "cut": 10}],
      "qual_flags": []
  }],
  "knowledge": [
      {"sku": "SKU001", "text": "含 5% 烟酰胺…", "keywords": ["烟酰胺", "保湿"]}
  ]
}
示例见 config/room.example.json。
"""
import json
from typing import Any, Dict, Tuple

from ..data.product_store import CouponRule, Product
from ..decision.knowledge_store import KnowledgeDoc


def load_room_data(brain, path: str) -> Tuple[int, int]:
    """加载直播间数据：返回 (商品数, 知识条数)。首个商品自动设为当前讲品。

    校验失败抛 ValueError（开播前发现，好过直播中翻车）。
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
    return len(products), len(knowledge)


def _yuan_to_cents(value: Any) -> int:
    return int(round(float(value) * 100))


def _require(item: Dict, keys: Tuple[str, ...], where: str) -> None:
    for key in keys:
        if key not in item:
            raise ValueError("%s 缺少必填字段 %s" % (where, key))
