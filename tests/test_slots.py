"""填槽制（DESIGN §6.3）：LLM 全程不接触真实数字。"""
from livebrain.decision import slots


def test_validate_ok():
    v = slots.validate_generated("这款到手只要{price}，喜欢的直接拍！")
    assert v.ok


def test_validate_raw_digits_rejected():
    v = slots.validate_generated("这款只要199元，买它！")
    assert not v.ok
    assert "raw_digits" in v.problems


def test_validate_unknown_slot_rejected():
    v = slots.validate_generated("包邮到{mars}星球")
    assert not v.ok
    assert any(p.startswith("unknown_slot") for p in v.problems)


def test_validate_digit_inside_slot_allowed():
    assert slots.validate_generated("库存只剩{stock}件").ok


def test_fill_ok():
    text, unfilled = slots.fill("只要{price}元，剩{stock}件",
                                {"price": "¥119", "stock": "30"})
    assert text == "只要¥119元，剩30件" and unfilled == []


def test_fill_missing_fact_returns_none():
    text, unfilled = slots.fill("只要{price}元", {})
    assert text is None and unfilled == ["price"]


def test_filled_text_has_no_slots():
    text, _ = slots.fill("{price}", {"price": "¥119"})
    assert slots.assert_no_raw_digits(text)
