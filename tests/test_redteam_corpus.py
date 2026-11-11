"""红队弹幕集回归（DESIGN §9）：资产文件驱动，每次改词表/模板全量回归。

资产：assets/redteam_danmu.jsonl（红队集是回归资产，不是一次性测试数据）。
"""
import json
import os

from livebrain.perception import classifier as C
from livebrain.perception.classifier import classify
from livebrain.perception.sanitizer import sanitize

_CORPUS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets", "redteam_danmu.jsonl")


def _load():
    cases = []
    with open(_CORPUS, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def test_corpus_size():
    cases = _load()
    assert len(cases) >= 38, "红队集应保持规模（当前 %d 条）" % len(cases)
    assert len({c["text"] for c in cases}) == len(cases), "样本不得重复"


def test_all_injection_quarantined():
    for case in _load():
        if case["category"] != "injection":
            continue
        result = sanitize(case["text"])
        assert result.quarantined, "注入样本未被隔离: %s" % case["text"]


def test_all_sensitive_routed_to_template():
    for case in _load():
        if case["category"] != "sensitive":
            continue
        assert sanitize(case["text"]).quarantined is False
        assert classify(case["text"]).intent == C.SENSITIVE, case["text"]


def test_all_action_request_routed_to_template():
    for case in _load():
        if case["category"] != "action":
            continue
        assert classify(case["text"]).intent == C.ACTION_REQUEST, case["text"]


def test_normal_danmu_safe():
    for case in _load():
        if case["category"] != "normal":
            continue
        result = sanitize(case["text"])
        assert not result.quarantined, "正常弹幕误伤: %s" % case["text"]
        intent = classify(result.cleaned)
        expected = case.get("expect_intent")
        if expected:
            assert intent.intent == expected, "%s -> %s" % (case["text"], intent.intent)


def test_no_normal_text_matches_injection_patterns():
    """防过度拦截：正常样本不得命中任何注入模式。"""
    normals = [c["text"] for c in _load() if c["category"] == "normal"]
    assert len(normals) >= 12
    for text in normals:
        assert not sanitize(text).quarantined
