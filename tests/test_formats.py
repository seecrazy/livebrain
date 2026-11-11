"""直播场景包（V4.4）：直播不一定是卖货。

覆盖：注册表/场景策略覆盖/主动推进（排品/话题/报幕/段子/对词）/
点歌版权白名单/段子被打断回炉/对词角色轮转/礼物感谢/非对应场景婉拒。
"""
import asyncio

from livebrain.config import Settings
from livebrain.events import GIFT, LiveEvent, danmu_event
from livebrain.formats import available, create
from livebrain.orchestrator import LiveBrain
from livebrain.perception import classifier as C
from livebrain.perception.classifier import classify
from livebrain.platform.mock_platform import MockPlatform


def _gift_event(room, user, gift, count=1):
    return LiveEvent(kind=GIFT, room_id=room, ts=0.0, priority=2,
                     payload={"user_id": user, "gift": gift, "count": count})


def _brain(fmt: str, proactive: int = 0) -> LiveBrain:
    settings = Settings(clock_scale=0.0, aggregate_window_s=0.4,
                        fast_reply_per_min=30, llm_reply_per_min=30,
                        proactive_after_ticks=proactive)
    brain = LiveBrain(platform=MockPlatform("room-%s" % fmt),
                      settings=settings, room_id="room-%s" % fmt,
                      format_id=fmt)
    return brain


async def _ticks(brain, n: int) -> None:
    for _ in range(n):
        await brain._tick()


# ---------------------------------------------------------------- 注册与意图
def test_registry_and_new_intents():
    assert available() == ["chat", "crosstalk", "ecommerce", "music", "standup"]
    assert create("standup").display_name == "单口相声·脱口秀"
    try:
        create("unknown")
    except ValueError as exc:
        assert "未知直播场景" in str(exc)
    else:
        raise AssertionError("未知场景必须报错")
    assert classify("唱一首月亮代表我的心").intent == C.SONG_REQUEST
    assert classify("来个段子").intent == C.JOKE_REQUEST


def test_format_strategy_and_display():
    brain = _brain("music")
    assert brain.field.strategy().emotion == "cheerful"     # 场景包覆盖生效
    brain = _brain("standup")
    assert brain.field.strategy().emotion == "playful"
    state = brain.state_snapshot()
    assert state["format"] == "standup"
    assert state["format_name"] == "单口相声·脱口秀"


# ---------------------------------------------------------------- 电商：排品推进
def test_ecommerce_proactive_product_push():
    brain = _brain("ecommerce", proactive=2)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 8))
    sources = [r.task.source for r in brain.speech_results]
    assert any(s == "format:joke" for s in sources) is False
    # 电商场景包主动推进复用兜底池（排品话术）
    assert any(r.task.origin == "排品推进" for r in brain.speech_results)


# ---------------------------------------------------------------- 聊天：话题
def test_chat_topics_rotate_without_repeat():
    brain = _brain("chat", proactive=2)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 14))
    topics = [r.spoken_text for r in brain.speech_results
              if r.task.source == "format:topic"]
    assert len(topics) >= 2
    assert len(set(topics)) == len(topics), "话题不重复"
    assert brain.format.stage_display["explain"] == "话题进行中"


# ---------------------------------------------------------------- 唱歌：点歌
def test_music_whitelist_and_queue():
    brain = _brain("music", proactive=2)
    asyncio.run(brain.start())

    async def scenario():
        await brain._handle(danmu_event("room-music", "u1",
                                        "唱一首月亮代表我的心", 0.1))
        await brain._handle(danmu_event("room-music", "u2",
                                        "来一首孤勇者", 0.2))       # 非白名单
        await brain._handle(danmu_event("room-music", "u3",
                                        "点一首朋友", 0.3))
        await _ticks(brain, 30)

    asyncio.run(scenario())
    sources = [(r.task.source, r.spoken_text) for r in brain.speech_results]
    # 白名单：确认入队
    assert any(s == "format:song_ack" and "月亮代表我的心" in t
               for s, t in sources)
    assert any(s == "format:song_ack" and "朋友" in t for s, t in sources)
    # 非白名单：版权婉拒（合规红线）
    declines = [t for s, t in sources if s == "format:song_decline"]
    assert declines and "授权" in declines[0]
    # 报幕按点歌顺序出队
    announces = [t for s, t in sources if s == "format:song_announce"]
    assert any("月亮代表我的心" in t for t in announces)
    assert any("朋友" in t for t in announces)
    assert announces.index(next(t for t in announces if "月亮" in t)) < \
           announces.index(next(t for t in announces if "朋友" in t))


# ---------------------------------------------------------------- 单口相声
def test_standup_joke_flow_and_interrupt_retry():
    brain = _brain("standup", proactive=2)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 6))
    jokes = [r for r in brain.speech_results if r.task.source == "format:joke"]
    assert jokes, "空闲主动讲段子"
    text = jokes[0].spoken_text
    assert "。" in text, "setup+punch 两句结构"

    # 点段子：即时应答
    async def request():
        await brain._handle(danmu_event("room-standup", "u1", "讲个段子", 0.1))
        await _ticks(brain, 6)

    asyncio.run(request())
    assert any(r.task.origin.startswith("段子:") for r in brain.speech_results)

    # 被打断的段子回炉重讲（确定性验证回滚语义）
    fmt = brain.format
    task = asyncio.run(fmt.proactive(brain))       # 取一段子，pos 前进
    probe = type("R", (), {"interrupted": True, "task": task,
                           "sentences_spoken": 0})()
    fmt.on_speech_done(brain, probe)                # 没开口就被打断 -> 整段回炉
    replay = asyncio.run(fmt.proactive(brain))
    assert replay.origin == task.origin, "同一段子应回炉重讲"
    assert replay.sentences == task.sentences


# ---------------------------------------------------------------- 多人相声
def test_crosstalk_alternating_roles():
    brain = _brain("crosstalk", proactive=2)
    asyncio.run(brain.start())
    asyncio.run(_ticks(brain, 20))
    beats = [r for r in brain.speech_results
             if r.task.source == "format:crosstalk"]
    assert len(beats) >= 3
    roles = [b.spoken_text[0] for b in beats]        # "A：..." / "B：..."
    assert "A" in roles and "B" in roles, "双角色出现"
    # 情绪随角色轮转（A=活泼 B=沉稳）
    emotions = [b.task.emotion for b in beats]
    assert "playful" in emotions and "steady" in emotions


# ---------------------------------------------------------------- 礼物感谢
def test_gift_thanks_all_formats():
    brain = _brain("chat")
    asyncio.run(brain.start())

    async def scenario():
        await brain._handle(_gift_event("room-chat", "老板张三", "火箭", 2))
        await _ticks(brain, 4)

    asyncio.run(scenario())
    thanks = [r for r in brain.speech_results
              if r.task.source == "format:gift_thanks"]
    assert thanks and "张三" in thanks[0].spoken_text and "火箭" in thanks[0].spoken_text
    assert brain.audit.count("gift") == 1


# ---------------------------------------------------------------- 婉拒（场景不匹配）
def test_decline_when_format_mismatch():
    brain = _brain("ecommerce")
    asyncio.run(brain.start())

    async def scenario():
        await brain._handle(danmu_event("room-ecommerce", "u1",
                                        "唱一首月亮代表我的心", 0.1))
        await _ticks(brain, 4)

    asyncio.run(scenario())
    sources = [r.task.source for r in brain.speech_results]
    assert "format:decline_song" in sources, "电商场不唱歌，礼貌婉拒"
