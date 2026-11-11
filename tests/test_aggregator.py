"""滑动窗口聚合 + 回复率预算（DESIGN §5.4）。"""
from livebrain.config import Settings
from livebrain.perception.aggregator import QuestionAggregator, ReplyBudget
from tests.helpers import FakeClock


def _agg(settings=None):
    clock = FakeClock()
    settings = settings or Settings(aggregate_window_s=15.0)
    return QuestionAggregator(settings, clock), clock


def test_price_question_immediate():
    agg, _clock = _agg()
    q = agg.add("price_stock", "price", "fast:price", "多少钱", "u1", False)
    assert q is not None and q.count == 1


def test_consult_merges_on_second():
    agg, _clock = _agg()
    assert agg.add("product_consult", "敏感", "consult:敏感",
                   "敏感肌能用吗", "u1", False) is None
    q = agg.add("product_consult", "敏感", "consult:敏感",
                "敏感肌可以用吗", "u2", False)
    assert q is not None
    assert q.count == 2
    assert q.is_multi
    assert set(q.user_ids) == {"u1", "u2"}


def test_consult_flush_after_window():
    agg, clock = _agg()
    assert agg.add("product_consult", "成分", "consult:成分",
                   "成分是什么", "u1", False) is None
    assert agg.flush_due() == []
    clock.advance(16.0)
    due = agg.flush_due()
    assert len(due) == 1 and due[0].count == 1


def test_representative_text_keeps_longer():
    agg, _clock = _agg()
    agg.add("product_consult", "敏感", "consult:敏感", "敏感肌", "u1", False)
    q = agg.add("product_consult", "敏感", "consult:敏感",
                "请问敏感肌可以用这款精华吗", "u2", False)
    assert q.representative_text == "请问敏感肌可以用这款精华吗"


def test_reply_budget_window():
    budget = ReplyBudget(fast_per_min=2, llm_per_min=1)
    clock = FakeClock()
    assert budget.allow("fast", clock.now())
    budget.consume("fast", clock.now())
    assert budget.allow("fast", clock.now())
    budget.consume("fast", clock.now())
    assert not budget.allow("fast", clock.now())
    clock.advance(61.0)
    assert budget.allow("fast", clock.now())
    assert budget.allow("llm", clock.now())   # llm 轨未消耗，仍可用
