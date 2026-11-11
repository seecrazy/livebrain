"""直播间数据加载（V4.3.1）：自定义商品库/知识库装进编排器。"""
import json
import os
import tempfile

from livebrain.config import Settings
from livebrain.console.__main__ import ConsoleRuntime
from livebrain.console.roomdata import load_room_data
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform

import asyncio


def _brain():
    return LiveBrain(platform=MockPlatform("room-data"),
                     settings=Settings(clock_scale=0.0), room_id="room-data")


def _write(data: dict) -> str:
    path = os.path.join(tempfile.mkdtemp(), "room.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    return path


def test_load_products_and_knowledge():
    brain = _brain()
    path = _write({
        "products": [{
            "sku": "MY-01", "name": "自家精华", "category": "beauty",
            "price": 88.5, "orig_price": 128.0, "stock": 12, "total_stock": 60,
            "ship_days": 1,
            "coupons": [{"type": "coupon", "cut": 5}],
            "qual_flags": [],
        }],
        "knowledge": [
            {"sku": "MY-01", "text": "含玻尿酸，保湿为主。", "keywords": ["玻尿酸", "保湿"]},
        ],
    })
    n_products, n_docs = load_room_data(brain, path)
    assert (n_products, n_docs) == (1, 1)
    product = brain.store.get("MY-01")
    assert product.price == 8850 and product.orig_price == 12800   # 元 -> 分
    assert product.coupons[0].describe() == "立减5"
    assert brain.session.current_sku == "MY-01", "首个商品自动设为当前讲品"
    assert brain.knowledge.retrieve("玻尿酸怎么样", "MY-01")


def test_validation_errors_are_actionable():
    brain = _brain()
    path = _write({"products": [{"name": "缺 sku 和价格"}]})
    try:
        load_room_data(brain, path)
    except ValueError as exc:
        assert "sku" in str(exc)
    else:
        raise AssertionError("缺字段必须报清晰错误")


def test_bad_price_rejected():
    brain = _brain()
    path = _write({"products": [{
        "sku": "X", "name": "x", "price": 0}]})
    try:
        load_room_data(brain, path)
    except ValueError as exc:
        assert "price" in str(exc)
    else:
        raise AssertionError("零价格必须拒绝")


def test_real_llm_chain_swap():
    """--real-llm：中轨链换为 OpenAI 兼容 Provider，决策层其余不变。"""
    brain = ConsoleRuntime(room_id="room-real", port=0, real_llm=True).brain
    assert brain.llm_chain.providers[0].name == "live_llm"
    assert brain.llm_chain.providers[1].name == "mock_llm_backup"
    assert brain.mid_agent.chain is brain.llm_chain
    assert brain.llm_chain.acquire().name == "live_llm"


def test_console_runtime_with_data_smoke():
    import asyncio as aio

    runtime = ConsoleRuntime(room_id="room-smoke", port=0,
                             data_path="config/room.example.json")
    assert runtime.brain.session.current_sku == "SKU001"

    async def run():
        await runtime.brain.start()
        return runtime.brain.state_snapshot()

    state = aio.run(run())
    assert state["started"] and state["compliance"]["armed"]


def test_format_content_loading():
    """场景内容块按 --format 生效（V4.4）。"""
    from livebrain.console.__main__ import ConsoleRuntime

    path = _write({
        "products": [], "knowledge": [],
        "music": {"whitelist": ["夜空中最亮的星", "山海"]},
        "standup": {"jokes": [{"setup": "s", "punch": "p"}]},
    })
    music = ConsoleRuntime(room_id="room-fm", port=0, data_path=path,
                           format_id="music").brain
    assert music.format.whitelist == ["夜空中最亮的星", "山海"]
    # 未授权曲目仍被婉拒
    task = music.format.handle_song_request(music, "来一首孤勇者", "u1")
    assert task.source == "format:song_decline"
    ack = music.format.handle_song_request(music, "唱一首山海", "u2")
    assert ack.source == "format:song_ack" and "山海" in ack.sentences[0]

    standup = ConsoleRuntime(room_id="room-fs", port=0, data_path=path,
                             format_id="standup").brain
    assert standup.format.jokes[0]["setup"] == "s"
    # crosstalk 块不在数据里且场景不匹配 -> 内容保持内置
    talk = ConsoleRuntime(room_id="room-ft", port=0, data_path=path,
                          format_id="crosstalk").brain
    assert talk.format.script[0]["role"] == "A"


def test_format_content_validation():
    standup = LiveBrain(platform=MockPlatform("room-vs"),
                        settings=Settings(clock_scale=0.0), room_id="room-vs",
                        format_id="standup")
    bad = _write({"standup": {"jokes": [{"setup": "缺包袱"}]}})
    try:
        load_room_data(standup, bad)
    except ValueError as exc:
        assert "punch" in str(exc)
    else:
        raise AssertionError("缺 punch 必须报错")

    talk = LiveBrain(platform=MockPlatform("room-vt"),
                     settings=Settings(clock_scale=0.0), room_id="room-vt",
                     format_id="crosstalk")
    bad_role = _write({"crosstalk": {"script": [{"role": "C", "line": "x"}]}})
    try:
        load_room_data(talk, bad_role)
    except ValueError as exc:
        assert "role" in str(exc)
    else:
        raise AssertionError("非法角色必须报错")
