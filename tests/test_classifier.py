"""意图预分类（DESIGN §5.3）。"""
from livebrain.perception import classifier as C
from livebrain.perception.classifier import classify


def test_price_subtype():
    r = classify("这个精华多少钱？")
    assert r.intent == C.PRICE_STOCK and r.subtype == C.SUB_PRICE


def test_stock_subtype():
    r = classify("还有货吗？库存多少")
    assert r.intent == C.PRICE_STOCK and r.subtype == C.SUB_STOCK


def test_ship_subtype():
    r = classify("什么时候发货")
    assert r.intent == C.PRICE_STOCK and r.subtype == C.SUB_SHIP


def test_coupon_subtype():
    r = classify("有优惠券吗，有满减吗")
    assert r.intent == C.PRICE_STOCK and r.subtype == C.SUB_COUPON


def test_consult():
    r = classify("敏感肌能用吗")
    assert r.intent == C.PRODUCT_CONSULT


def test_sensitive_beats_price():
    """敏感宣称优先于价格：哪怕句子里有钱字也不进生成路径。"""
    r = classify("这个多少钱？吃了能降血糖吗")
    assert r.intent == C.SENSITIVE


def test_action_request():
    r = classify("你敢保证有效吗")
    assert r.intent == C.ACTION_REQUEST


def test_purchase_intent_only_routes_to_fast():
    r = classify("怎么拍？有链接吗")
    assert r.purchase_intent
    assert r.intent == C.PRICE_STOCK and r.subtype == C.SUB_PRICE


def test_purchase_intent_flag():
    r = classify("多少钱？怎么拍")
    assert r.purchase_intent and r.intent == C.PRICE_STOCK


def test_interact():
    assert classify("主播晚上好呀").intent == C.INTERACT
    assert classify("你是数字人吗").intent == C.INTERACT


def test_noise():
    assert classify("。。。").intent == C.NOISE
    assert classify("🤡🤡").intent == C.NOISE
