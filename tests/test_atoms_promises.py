"""话术原子与承诺队列（DESIGN §6.6 / R5）。"""
import asyncio

from livebrain.data.audit import AuditLog
from livebrain.decision.atoms import (OpsAction, PromiseQueue,
                                      UnboundPromiseError, expand)
from livebrain.platform.mock_platform import MockPlatform
from tests.helpers import FakeClock


def test_expand_atom_with_ops():
    text, ops = expand("要的抓紧！[atom:link_up]")
    assert "三、二、一" in text
    assert len(ops) == 1 and ops[0].action == "link_up"


def test_expand_plain_text_no_ops():
    text, ops = expand("这款主打保湿哈")
    assert text == "这款主打保湿哈" and ops == []


def test_unbound_promise_words_blocked():
    try:
        expand("这款保证有效，放心冲！")
    except UnboundPromiseError as exc:
        assert "保证" in exc.words
    else:
        raise AssertionError("自由文本承诺词必须被拦截")


def test_promise_word_inside_atom_template_allowed():
    # 原子模板是策展内容，其中的承诺词不受自由文本扫描限制
    text, _ops = expand("[atom:coupon_5] 这款性价比很高")
    assert "优惠券" in text


def _queue(clock=None):
    clock = clock or FakeClock()
    audit = AuditLog()
    return PromiseQueue(clock, audit, deadline_s=30.0, room_id="r1"), clock, audit


def test_promise_fulfilled_via_platform():
    queue, _clock, audit = _queue()
    promise = queue.submit(OpsAction("link_up", {"sku": "SKU001"}), "utt-1")
    platform = MockPlatform("r1")
    asyncio.run(queue.execute_pending(platform))
    assert promise.status == "fulfilled"
    assert platform.ops_log and platform.ops_log[0]["action"] == "link_up"
    assert audit.count("promise") >= 2   # created + fulfilled


def test_promise_expired_alerts():
    clock = FakeClock()
    queue, _clock, audit = _queue(clock)
    promise = queue.submit(OpsAction("coupon", {"amount": 5}), "utt-1")
    clock.advance(31.0)
    asyncio.run(queue.execute_pending(MockPlatform("r1")))
    assert promise.status == "expired"
    assert any("promise_expired" in a for a in queue.alerts)


def test_promise_execute_rejected_keeps_pending():
    queue, _clock, _audit = _queue()
    promise = queue.submit(OpsAction("coupon", {}), "utt-1")
    platform = MockPlatform("r1", ops_failure_rate=1.0)   # 奇数成功偶数失败 -> 全失败
    asyncio.run(queue.execute_pending(platform))
    assert promise.status == "pending" and promise.failures >= 1
