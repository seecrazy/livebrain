"""快轨规则引擎（DESIGN §6.4）：数字的单一来源。"""
from livebrain.config import Settings
from livebrain.data.product_store import ProductStore, Product, seed_default
from livebrain.decision.field_controller import EXPLAIN, CLOSING, STRATEGIES
from livebrain.decision.rule_engine import (PromotionCalculator,
                                            RuleEngine, price_text)
from livebrain.perception.aggregator import AggregatedQuestion
from tests.helpers import FakeClock


def _question(subtype, text="多少钱", count=1):
    return AggregatedQuestion(
        intent="price_stock", subtype=subtype, topic_key="fast:" + subtype,
        representative_text=text, count=count, user_ids=["u1"])


def _engine(stale_after=30.0):
    clock = FakeClock(start=2000000.0)
    store = ProductStore()
    seed_default(store, clock.now())
    settings = Settings(stale_after_s=stale_after)
    return RuleEngine(store, settings, clock), store, clock


def test_promotion_calculation():
    store = ProductStore()
    seed_default(store, 0.0)
    product = store.get("SKU001")           # 12900，满100减10
    final, breakdown = PromotionCalculator.calculate(product)
    assert final == 11900
    assert breakdown == ["满100减10"]
    assert price_text(final) == "¥119"


def test_price_answer_contains_exact_price():
    engine, _store, _clock = _engine()
    task = engine.answer(_question("price"), "SKU001", STRATEGIES[EXPLAIN])
    assert "¥119" in task.sentences[0]
    assert "满100减10" in task.sentences[0]
    assert task.track == "fast"


def test_closing_stage_uses_urgency_and_link_atom():
    engine, _store, _clock = _engine()
    task = engine.answer(_question("price"), "SKU001", STRATEGIES[CLOSING])
    assert any("[atom:link_up]" in s for s in task.sentences)
    assert task.emotion == "urgent"


def test_multi_question_prefix():
    engine, _store, _clock = _engine()
    task = engine.answer(_question("price", count=3), "SKU001", STRATEGIES[EXPLAIN])
    assert "好多宝宝" in task.sentences[0]


def test_stale_snapshot_never_speaks_numbers():
    engine, store, clock = _engine(stale_after=30.0)
    store.get("SKU001").updated_at = clock.now() - 60.0
    task = engine.answer(_question("price"), "SKU001", STRATEGIES[EXPLAIN])
    assert task.source == "rule_stale"
    joined = "".join(task.sentences)
    assert "¥" not in joined and "119" not in joined
    assert "确认" in joined
    assert store.get("SKU001").version == 2   # 触发过刷新


def test_missing_product_conservative():
    engine, _store, _clock = _engine()
    task = engine.answer(_question("price"), "SKU-NONE", STRATEGIES[EXPLAIN])
    assert task.source == "rule_missing"


def test_low_stock_guardrail():
    engine, store, clock = _engine()
    product = store.get("SKU001")
    product.stock = 5                        # 5/50 = 10% < 20%
    task = engine.answer(_question("stock"), "SKU001", STRATEGIES[EXPLAIN])
    joined = "".join(task.sentences)
    assert "以订单页为准" in joined
    assert "5" in joined                     # 数字来自查询，逐字匹配


def test_ship_answer():
    engine, _store, _clock = _engine()
    task = engine.answer(_question("ship"), "SKU001", STRATEGIES[EXPLAIN])
    assert "2" in task.sentences[0] and "发货" in task.sentences[0]
