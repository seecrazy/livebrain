"""AI 内容创作（V4.4.1）：不指定内容时 AI 自己思考，失败回落内置。

优先级链：用户内容（--data）> AI 原创 > 内置种子。版权曲库不可 AI 生成。
"""
import asyncio
import json
import os
import tempfile

from livebrain.config import Settings
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform

JOKE_SCRIPT = {"脱口秀": "我给自己定了个AI目标，每天学一样新东西。"
                        "学到现在，唯一学会的就是怎么取消订阅。"}
EXTREME_SCRIPT = {"脱口秀": "这是史上最好笑的段子，全网第一。"}   # 极限词
TOPIC_SCRIPT = {"当前阶段": "评论区说说，你手机的电量现在剩多少？"}
BEAT_SCRIPT = {"续写": "嗐，那是它比你懂生活。"}


def _brain(fmt: str, script: dict, creative: bool = True,
           proactive: int = 3) -> LiveBrain:
    settings = Settings(clock_scale=0.0, aggregate_window_s=0.4,
                        fast_reply_per_min=30, llm_reply_per_min=30,
                        proactive_after_ticks=proactive,
                        creative_llm=creative)
    return LiveBrain(platform=MockPlatform("room-cr"),
                     settings=settings, room_id="room-cr",
                     llm_script=script, format_id=fmt)


async def _ticks(brain, n: int) -> None:
    for _ in range(n):
        await brain._tick()


def test_ai_joke_generated_and_digits_allowed():
    brain = _brain("standup", JOKE_SCRIPT)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 8))
    ai = [r for r in brain.speech_results if r.task.source == "format:joke_ai"]
    assert ai, "AI 原创段子出稿"
    assert "取消订阅" in ai[0].spoken_text
    assert brain.audit.count("creative_generated") >= 1


def test_ai_content_filtered_falls_back_to_seed():
    brain = _brain("standup", EXTREME_SCRIPT)     # 极限词 -> 过滤 -> 回落内置
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 8))
    assert any(r.task.source == "format:joke" for r in brain.speech_results), \
        "过滤失败必须回落内置段子，不冷场"
    assert brain.audit.count("creative_fallback") >= 1


def test_ai_topic_generated():
    brain = _brain("chat", TOPIC_SCRIPT)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 8))
    assert any(r.task.source == "format:topic_ai" for r in brain.speech_results)
    assert "电量" in "".join(r.spoken_text for r in brain.speech_results)


def test_ai_crosstalk_beat_alternates_roles_with_context():
    brain = _brain("crosstalk", BEAT_SCRIPT)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 14))
    beats = [r for r in brain.speech_results
             if r.task.source == "format:crosstalk_ai"]
    assert len(beats) >= 2, "AI 续对词"
    roles = [b.spoken_text[0] for b in beats]
    assert set(roles) >= {"A", "B"} or roles == sorted(roles), "角色轮转"
    # prompt 携带上文（续写需要语境）
    seen = "\n".join(brain.llm_seen_user_inputs())
    assert "最近对词" in seen or "逗哏" in seen


def test_user_content_beats_ai():
    path = os.path.join(tempfile.mkdtemp(), "room.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"standup": {"jokes": [
            {"id": "u1", "setup": "用户自己的铺垫。", "punch": "用户自己的包袱。"}]}},
            fh, ensure_ascii=False)
    brain = _brain("standup", JOKE_SCRIPT)
    from livebrain.console.roomdata import load_room_data
    load_room_data(brain, path)
    assert brain.format._user_content
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 8))
    sources = {r.task.source for r in brain.speech_results}
    assert "format:joke" in sources and "format:joke_ai" not in sources, \
        "用户内容优先，AI 不抢戏"


def test_creative_off_uses_seed():
    brain = _brain("standup", JOKE_SCRIPT, creative=False)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 8))
    assert any(r.task.source == "format:joke" for r in brain.speech_results)
    assert all(r.task.source != "format:joke_ai"
               for r in brain.speech_results)


def test_music_whitelist_never_ai():
    """版权白名单不可 AI 生成：未指定时只用内置曲库。"""
    brain = _brain("music", {}, creative=True)
    assert brain.format.whitelist == list(brain.format.WHITELIST)
    asyncio.run(brain.start())
    task = brain.format.handle_song_request(brain, "来一首孤勇者", "u1")
    assert task.source == "format:song_decline", "内置白名单外依旧婉拒"
