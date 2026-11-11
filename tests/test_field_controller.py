"""场控阶段状态机（DESIGN §6.8）：滞回切换。"""
from livebrain.config import Settings
from livebrain.decision.field_controller import (CLOSING, EXPLAIN, VALLEY,
                                                 WARMUP, FieldController)


def _controller():
    return FieldController(Settings(hysteresis_ticks=2, warmup_online=50,
                                    low_stock_ratio=0.2, valley_drop_ratio=0.3))


def test_warmup_to_explain_needs_two_ticks():
    fc = _controller()
    assert fc.update(online=60, stock_ratio=0.9) is None   # 第 1 个周期
    change = fc.update(online=60, stock_ratio=0.9)          # 第 2 个周期触发
    assert change == (WARMUP, EXPLAIN, "online>=warmup_threshold")


def test_explain_to_closing_on_low_stock():
    fc = _controller()
    fc.update(60, 0.9); fc.update(60, 0.9)
    assert fc.update(60, 0.15) is None
    change = fc.update(60, 0.15)
    assert change[1] == CLOSING and "stock" in change[2]


def test_closing_back_to_explain_on_recover():
    fc = _controller()
    fc.update(60, 0.9); fc.update(60, 0.9)
    fc.update(60, 0.15); fc.update(60, 0.15)
    assert fc.update(60, 0.6) is None
    assert fc.update(60, 0.6)[1] == EXPLAIN


def test_valley_on_online_drop():
    fc = _controller()
    fc.update(100, 0.9); fc.update(100, 0.9)     # peak=100 -> EXPLAIN
    assert fc.update(60, 0.9) is None            # 下降 40% > 30%，第 1 周期
    assert fc.update(60, 0.9)[1] == VALLEY


def test_valley_recovery_resets_peak():
    fc = _controller()
    fc.update(100, 0.9); fc.update(100, 0.9)
    fc.update(60, 0.9); fc.update(60, 0.9)       # -> VALLEY, peak=100
    assert fc.update(75, 0.9) is None
    assert fc.update(75, 0.9)[1] == EXPLAIN      # 75 > 70%*100
    assert fc.peak_online == 75                  # 峰值基准重置


def test_strategy_per_stage():
    fc = _controller()
    assert fc.strategy().interact_reply_ratio == 1.0     # warmup
    fc.update(60, 0.9); fc.update(60, 0.9)
    assert fc.strategy().name == EXPLAIN
    assert fc.strategy().interact_reply_ratio == 0.2


def test_flicker_does_not_switch():
    """指标抖动一个周期不切阶段（滞回）。"""
    fc = _controller()
    fc.update(60, 0.9)              # want=EXPLAIN tick1
    fc.update(10, 0.9)              # 回到不足 -> 重置
    assert fc.stage == WARMUP
    fc.update(60, 0.9)              # 重新 tick1
    assert fc.update(60, 0.9)[1] == EXPLAIN
