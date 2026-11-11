"""三道过滤 + 品类宣称引擎（DESIGN §6.5 / R11）。"""
from livebrain.decision.filters import check, check_claims


def test_absolute_banned():
    r = check("想买的加微信私聊")
    assert not r.passed and any("banned" in b for b in r.blocked)


def test_extreme_words():
    r = check("全网最低价，史上最强")
    assert not r.passed and any("extreme" in b for b in r.blocked)


def test_food_category_forbidden_claims():
    r = check("这款软糖能降血糖", category="food")
    assert not r.passed
    assert any("降血糖" in b for b in r.blocked)


def test_supplement_needs_qualification():
    # 无蓝帽子旗标：宣称被拦
    r = check("这款片剂帮助降血压", category="supplement", qual_flags=[])
    assert not r.passed and any("needs_qual" in b for b in r.blocked)
    # 有旗标：放行
    r2 = check("这款片剂帮助降血压", category="supplement",
               qual_flags=["blue_hat"])
    assert r2.passed


def test_beauty_medical_wording_blocked():
    assert not check("医疗级配方，药用级别", category="beauty").passed


def test_clean_text_passes_all():
    assert check("这款精华主打保湿，具体以详情页为准", category="beauty").passed


def test_check_claims_unknown_category_lenient():
    assert check_claims("任意表述", "unknown_cat", []) == []
