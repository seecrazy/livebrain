"""商品库：数字的单一事实来源（DESIGN §8.1）。

- 价格用「分」存整数，杜绝浮点误差；
- 快照带版本号与时间戳，规则引擎播报前做新鲜度校验（R12）；
- 品类/资质旗标驱动宣称过滤（R11）；
- LLM 轨不直连本库，只有规则引擎可读数字字段。
M1 内存实现，接口按 PostgreSQL 设计，M2 平移。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class CouponRule:
    rule_type: str          # full_cut（满减）/ coupon（直减）
    threshold: int = 0      # 分
    cut: int = 0            # 分

    def describe(self) -> str:
        if self.rule_type == "full_cut":
            return "满%s减%s" % (_fmt(self.threshold), _fmt(self.cut))
        return "立减%s" % _fmt(self.cut)


def _fmt(cents: int) -> str:
    yuan = cents / 100.0
    if cents % 100 == 0:
        return "%d" % (cents // 100)
    return ("%.2f" % yuan).rstrip("0").rstrip(".")


@dataclass
class Product:
    sku: str
    name: str
    category: str                       # food / beauty / supplement / ...
    price: int                          # 分
    orig_price: int                     # 分
    stock: int
    total_stock: int
    ship_days: int
    coupons: List[CouponRule] = field(default_factory=list)
    qual_flags: List[str] = field(default_factory=list)   # 如 blue_hat
    version: int = 1
    updated_at: float = 0.0

    def stock_ratio(self) -> float:
        if self.total_stock <= 0:
            return 0.0
        return self.stock / float(self.total_stock)


class ProductStore:
    def __init__(self) -> None:
        self._products: Dict[str, Product] = {}

    def upsert(self, product: Product) -> None:
        self._products[product.sku] = product

    def get(self, sku: str) -> Optional[Product]:
        return self._products.get(sku)

    def bump_version(self, sku: str, now: float) -> None:
        """模拟一次刷新（M2 接真实库存拉取）。"""
        product = self._products.get(sku)
        if product:
            product.version += 1
            product.updated_at = now

    def snapshot_age(self, sku: str, now: float) -> Optional[float]:
        product = self._products.get(sku)
        if product is None:
            return None
        if product.updated_at <= 0:
            return 0.0
        return now - product.updated_at


def seed_default(store: ProductStore, now: float) -> None:
    """默认演示商品：美妆精华（低库存触发逼单）+ 食品软糖。"""
    store.upsert(Product(
        sku="SKU001", name="烟酰胺焕亮精华", category="beauty",
        price=12900, orig_price=15900, stock=30, total_stock=50, ship_days=2,
        coupons=[CouponRule("full_cut", 10000, 1000)],
        qual_flags=[], updated_at=now))
    store.upsert(Product(
        sku="SKU002", name="蓝莓叶黄素酯软糖", category="food",
        price=9900, orig_price=12900, stock=40, total_stock=50, ship_days=3,
        coupons=[], qual_flags=[], updated_at=now))
