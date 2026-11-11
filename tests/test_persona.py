"""人设与情绪管理（DESIGN §6.9）。"""
from livebrain.config import Settings
from livebrain.decision.persona import PersonaManager


def _manager():
    return PersonaManager(Settings(manual_persona_switch_limit=2))


def test_manual_switch_within_limit():
    pm = _manager()
    ok, _ = pm.switch("ajing", source="manual")
    assert ok and pm.current.persona_id == "ajing"
    ok, _ = pm.switch("xiaotian", source="manual")
    assert ok


def test_manual_switch_limit_reached():
    pm = _manager()
    pm.switch("ajing", source="manual")
    pm.switch("xiaotian", source="manual")
    ok, reason = pm.switch("ajing", source="manual")
    assert not ok and reason == "manual_limit_reached"


def test_auto_switch_requires_stage_boundary():
    pm = PersonaManager(Settings())
    ok, reason = pm.switch("ajing", source="auto")
    assert not ok and reason == "auto_requires_stage_boundary"
    ok, _ = pm.switch("ajing", source="auto", stage_boundary=True)
    assert ok


def test_unknown_persona_rejected():
    pm = PersonaManager(Settings())
    assert pm.switch("nobody", source="manual")[0] is False


def test_decorate_digit_free_and_periodic():
    pm = PersonaManager(Settings())
    seen = []
    for i in range(6):
        text = pm.decorate("这款主打保湿")
        assert not any(ch.isdigit() for ch in text)   # 口头禅必须数字无关
        seen.append(text)
    # 每 3 句追加一次口头禅
    assert "宝宝们" in seen[2] and "宝宝们" not in seen[1]


def test_decorate_no_duplicate_catchphrase():
    pm = PersonaManager(Settings())
    pm._utterance_seq = 2   # 下一句是第 3 句
    text = pm.decorate("宝宝们看这款")
    assert text.count("宝宝们") == 1
