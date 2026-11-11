"""批1 可靠性与性能：tick 防护/心跳/批量 drain/审计批量 flush/推流看护。"""
import asyncio
import os
import tempfile
import time

from livebrain.config import Settings
from livebrain.data.audit import AuditLog
from livebrain.events import danmu_event
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform


def _brain():
    return LiveBrain(platform=MockPlatform("room-rp"),
                     settings=Settings(clock_scale=0.0), room_id="room-rp")


# ------------------------------------------------ tick 顶层防护 + 心跳
def test_tick_guard_survives_exception_with_heartbeat():
    brain = _brain()

    async def scenario():
        await brain.start()
        await brain._tick()                       # 正常 tick：心跳刷新
        assert brain.last_tick_ts > 0
        original = brain._handle_danmu
        async def boom(event):
            raise RuntimeError("注入的偶发异常")
        brain._handle_danmu = boom
        brain.bus.publish(danmu_event("room-rp", "u1", "这个精华多少钱", 0.1))
        alive = await brain._tick()               # 异常不得杀死循环
        brain._handle_danmu = original
        return alive

    alive = asyncio.run(scenario())
    assert alive, "异常后 tick 必须继续存活"
    assert brain.tick_errors == 1
    assert brain.audit.count("tick_error") == 1
    assert any(a.startswith("TICK_ERROR") for a in brain.alerts)
    state = brain.state_snapshot()
    assert state["heartbeat"]["tick_errors"] == 1
    assert state["heartbeat"]["age_s"] >= 0


def test_heartbeat_and_minute_stats_in_snapshot():
    brain = _brain()

    async def scenario():
        await brain.start()
        await brain._tick()
        brain.bus.publish(danmu_event("room-rp", "u1", "主播晚上好", 0.1))
        await brain._tick()
        return brain.state_snapshot()

    state = asyncio.run(scenario())
    assert state["heartbeat"]["age_s"] < 3
    assert state["stats"]["danmu_last_min"] >= 1


# ------------------------------------------------ 批量 drain
def test_bus_batch_drain():
    brain = _brain()

    async def scenario():
        await brain.start()
        for i in range(20):
            brain.bus.publish(danmu_event(
                "room-rp", "u%d" % i, "第%d条弹幕哈哈哈" % i, 0.1))
        await brain._tick()                       # 单 tick 应消化大部分
        return len(brain.bus)

    remaining = asyncio.run(scenario())
    assert remaining <= 8, "单 tick 应批量处理至少 12 条（剩 %d）" % remaining


# ------------------------------------------------ 审计批量 flush
def test_audit_batched_flush():
    path = os.path.join(tempfile.mkdtemp(), "audit.jsonl")
    audit = AuditLog(path)
    for i in range(5):
        audit.append("utterance", "r", {"i": i})
    # 未到阈值（20 条/1 秒）：允许尚未落盘
    with open(path, encoding="utf-8") as fh:
        early = len(fh.read().strip().splitlines()) if os.path.getsize(path) else 0
    for i in range(20):
        audit.append("utterance", "r", {"i": 100 + i})
    with open(path, encoding="utf-8") as fh:
        lines = [x for x in fh.read().splitlines() if x.strip()]
    audit.close()
    assert len(lines) >= 20, "满 20 条必须已落盘（实际 %d，early=%d）" % (
        len(lines), early)
    import json
    assert all(json.loads(x)["type"] == "utterance" for x in lines)


# ------------------------------------------------ 推流看护
def test_streamer_watchdog_restart_and_disable():
    from livebrain.console.__main__ import ConsoleRuntime

    class FakeStreamer:
        def __init__(self):
            self.dead = False
            self.stopped = 0

        def healthy(self):
            return not self.dead

        def say(self, *a, **k):
            pass

        def stop(self):
            self.stopped += 1

    runtime = ConsoleRuntime(room_id="room-wd", port=0)
    fake = FakeStreamer()
    runtime.streamer = fake
    runtime.rtmp = "/tmp/x.flv"

    import livebrain.console.__main__ as m
    original_ctor = m.LowFiStreamer if hasattr(m, "LowFiStreamer") else None
    restarts = []

    def fake_ctor(target):
        restarts.append(target)
        new_one = FakeStreamer()
        return new_one

    # _watch_streamer 里局部 import LowFiStreamer —— monkeypatch 模块级符号
    import livebrain.streaming.lowfi as lowfi_mod
    original_lowfi = lowfi_mod.LowFiStreamer
    lowfi_mod.LowFiStreamer = fake_ctor
    try:
        runtime._watch_streamer()               # 健康：不动
        assert runtime.streamer is fake and fake.stopped == 0
        fake.dead = True
        runtime._watch_streamer()               # 第一次崩：重启
        assert len(restarts) == 1 and runtime._streamer_restarts == 1
        runtime.streamer.dead = True
        runtime._watch_streamer()               # 第二次崩：重启
        assert runtime._streamer_restarts == 2
        runtime.streamer.dead = True
        runtime._watch_streamer()               # 第三次崩：停用保画面
        assert runtime.streamer is None and runtime._streamer_failed
        state = {}
        runtime._extra_state()
        assert runtime._extra_state()["rtmp_status"] == "off"
    finally:
        lowfi_mod.LowFiStreamer = original_lowfi
