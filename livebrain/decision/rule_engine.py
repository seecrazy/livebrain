"""快轨规则引擎（DESIGN §6.4）：确定性问答，完全绕过 LLM。

铁律：
- 禁止生成任何未经数据库查询的数字；
- 价格/库存/优惠逐字匹配促销计算结果；
- 快照过期返回"确认中"话术并触发刷新，不得播报过期数字；
- 临界库存固定挂"以订单页为准"兜底句。
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..config import Settings
from ..data.product_store import Product, ProductStore, _fmt
from ..perception.aggregator import AggregatedQuestion
from ..perception.classifier import (SUB_COUPON, SUB_PRICE, SUB_SHIP, SUB_STOCK)
from ..util import uid
from . import slots
from .field_controller import CLOSING, StageStrategy
from .types import PRIORITY_FAST, OpsAction, SpeechTask, TRACK_FAST


class PromotionCalculator:
    """优惠叠加：按声明顺序应用满减/直减，输出明细。"""

    @staticmethod
    def calculate(product: Product) -> Tuple[int, List[str]]:
        final = product.price
        breakdown: List[str] = []
        for rule in product.coupons:
            if rule.rule_type == "full_cut":
                if final >= rule.threshold:
                    final -= rule.cut
                    breakdown.append(rule.describe())
            elif rule.rule_type == "coupon":
                final = max(0, final - rule.cut)
                breakdown.append(rule.describe())
        return final, breakdown


def price_text(cents: int) -> str:
    return "¥" + _fmt(cents)


# 快轨模板（策展内容，含占位符；原子引用只在指定位置出现）
_T_PRICE = "{product_name}现在到手只要{price}，日常价{orig_price}，{coupon}，喜欢的直接拍！"
_T_PRICE_MULTI = "好多宝宝在问价格～{product_name}到手只要{price}，{coupon}，直接拍！"
_T_PRICE_CLOSING = "库存告急！{product_name}到手{price}，{coupon}，要的宝宝抓紧！[atom:link_up]"
_T_GUARD = "就剩{stock}件了，最终以订单页为准哈！"
_T_STOCK = "{product_name}现在还剩{stock}件～"
_T_STOCK_LOW = "库存告急！就剩{stock}件了，最终以订单页为准！"
_T_SHIP = "下单后{ship_days}个工作日内发货哈～"
_T_COUPON = "现在有{coupon}，叠加后到手{price}～"
_T_CONFIRM = "稍等哈，我确认一下最新信息，宝宝们别急～"
_T_MISSING = "这款我确认一下哈，信息以订单页为准～"


class RuleEngine:
    def __init__(self, store: ProductStore, settings: Settings, clock) -> None:
        self.store = store
        self.settings = settings
        self.clock = clock

    def _stale(self, product: Product) -> bool:
        age = self.store.snapshot_age(product.sku, self.clock.now())
        return age is None or age > self.settings.stale_after_s

    def answer(self, question: AggregatedQuestion, sku: str,
               strategy: StageStrategy) -> SpeechTask:
        product = self.store.get(sku)
        now = self.clock.now()
        if product is None:
            return self._task([_T_MISSING], {}, question, source="rule_missing")
        if self._stale(product):
            self.store.bump_version(sku, now)   # 触发刷新，本次不播过期数字
            return self._task([_T_CONFIRM], {}, question, source="rule_stale")

        subtype = question.subtype or SUB_PRICE
        facts: Dict[str, str] = {"product_name": product.name}
        low = product.stock_ratio() < self.settings.low_stock_ratio
        texts: List[str] = []
        emotion = strategy.emotion

        if subtype == SUB_PRICE:
            final, breakdown = PromotionCalculator.calculate(product)
            facts.update({
                "price": price_text(final),
                "orig_price": price_text(product.orig_price),
                "coupon": "、".join(breakdown) if breakdown else "没有额外优惠券",
                "stock": str(product.stock),
            })
            if strategy.name == CLOSING or low:
                texts.append(_T_PRICE_CLOSING)
                emotion = "urgent"
            elif question.is_multi:
                texts.append(_T_PRICE_MULTI)
            else:
                texts.append(_T_PRICE)
            if low and strategy.name != CLOSING:
                texts.append(_T_GUARD)
        elif subtype == SUB_STOCK:
            facts["stock"] = str(product.stock)
            texts.append(_T_STOCK_LOW if low else _T_STOCK)
            if low:
                emotion = "urgent"
        elif subtype == SUB_SHIP:
            facts["ship_days"] = str(product.ship_days)
            texts.append(_T_SHIP)
        else:  # coupon
            final, breakdown = PromotionCalculator.calculate(product)
            facts.update({
                "coupon": "、".join(breakdown) if breakdown else "暂时没有优惠券",
                "price": price_text(final),
            })
            texts.append(_T_COUPON)

        filled: List[str] = []
        for template in texts:
            text, unfilled = slots.fill(template, facts)
            if text is None:  # 模板与 facts 不匹配属于编程错误，保守降级
                return self._task([_T_MISSING], facts, question,
                                  source="rule_fill_error")
            filled.append(text)

        return self._task(filled, facts, question, source="rule_engine",
                          emotion=emotion)

    def _task(self, sentences: List[str], facts: Dict[str, str],
              question: AggregatedQuestion, source: str,
              emotion: str = "steady") -> SpeechTask:
        return SpeechTask(
            task_id=uid("spk"), track=TRACK_FAST, sentences=sentences,
            priority=PRIORITY_FAST, emotion=emotion, ops=[],
            origin=question.representative_text, source=source,
            facts=facts, created_ts=self.clock.now())
