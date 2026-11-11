"""混播引擎（V4.2，DESIGN §7.7）：排班切换 / 真人画面 / 标识策略 / 承诺阻塞。"""
import asyncio

from livebrain.config import Settings
from livebrain.decision.types import OpsAction
from livebrain.events import control_event, danmu_event, metric_event
from livebrain.execution.compliance import ComplianceProfile
from livebrain.mixed.capture import MockHumanCapture
from livebrain.mixed.schedule import MixedSchedule, ScheduleSegment
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform
from tests.helpers import FakeClock


# ---------------------------------------------------------------- 排班器单元
def test_schedule_boundaries_and_pending():
    schedule = MixedSchedule([
        ScheduleSegment(10, "ai", "暖场"),
        ScheduleSegment(20, "human", "主推真人场"),
        ScheduleSegment(5, "ai", "返场"),
    ])
    schedule.begin(0.0)
    assert schedule.pending(5) and schedule.current_mode() == "ai"
    assert schedule.poll(5) == []
    transitions = schedule.poll(10)
    assert transitions == [{"to": "human", "from": "ai", "label": "主推真人场",
                            "boundary_s": 10}]
    assert schedule.current_mode() == "human"
    assert schedule.poll(12) == []
    assert schedule.poll(31) == [{"to": "ai", "from": "human", "label": "返场",
                                  "boundary_s": 30}]
    assert not schedule.pending(36)


def test_schedule_same_mode_no_event():
    schedule = MixedSchedule([ScheduleSegment(5, "ai"), ScheduleSegment(5, "ai")])
    schedule.begin(0.0)
    assert schedule.poll(6) == []          # 同模相邻段不产生切换
    assert not schedule.pending(6)


def test_schedule_multi_advance_in_one_poll():
    schedule = MixedSchedule([ScheduleSegment(1, "ai"), ScheduleSegment(1, "human"),
                              ScheduleSegment(1, "ai")])
    schedule.begin(0.0)
    transitions = schedule.poll(10)        # 时间跳跃跨多个边界
    assert [t["to"] for t in transitions] == ["human", "ai"]


# ---------------------------------------------------------------- 集成
class _HookBrain(LiveBrain):
    """在切换点注入确定性弹幕/承诺，模拟真人在场时的观众输入。"""

    inject_on_human = None
    inject_on_exit_human = None
    submit_promise_on_human = False

    async def _enter_human(self, reason):
        await LiveBrain._enter_human(self, reason)
        if self.submit_promise_on_human:
            self.promises.submit(OpsAction("link_up", {}), "utt-mixed")
        if _HookBrain.inject_on_human:
            self.bus.publish(danmu_event(self.room_id, "watcher",
                                         _HookBrain.inject_on_human, 0.0))

    async def _exit_human(self, force=False, reason="manual"):
        result = await LiveBrain._exit_human(self, force=force, reason=reason)
        if result and _HookBrain.inject_on_exit_human:
            self.bus.publish(danmu_event(self.room_id, "watcher2",
                                         _HookBrain.inject_on_exit_human, 0.0))
        return result


def _mixed_settings():
    return Settings(clock_scale=0.0, aggregate_window_s=0.4,
                    fast_reply_per_min=30, llm_reply_per_min=30,
                    breaker_threshold=3,
                    mixed_schedule=[
                        {"duration_s": 0.15, "mode": "ai", "label": "AI 暖场"},
                        {"duration_s": 0.30, "mode": "human", "label": "真人主推"},
                        {"duration_s": 0.15, "mode": "ai", "label": "AI 返场"},
                    ])


def test_mixed_schedule_end_to_end():
    _HookBrain.inject_on_human = "这个精华多少钱？"
    _HookBrain.inject_on_exit_human = "这个精华多少钱？"
    try:
        platform = MockPlatform("room-mixed", human_capture=MockHumanCapture())
        brain = _HookBrain(platform=platform, settings=_mixed_settings(),
                           room_id="room-mixed")
        brain.schedule(0.05, metric_event("room-mixed", 0.1, 120, 0.6))
        brain.schedule(0.05, danmu_event("room-mixed", "u1", "主播晚上好呀", 0.2))
        asyncio.run(brain.run_until_idle())
    finally:
        _HookBrain.inject_on_human = None
        _HookBrain.inject_on_exit_human = None

    audit = brain.audit
    log = brain.pipeline.log
    sources = [r.task.source for r in brain.speech_results]

    # 排班切换：进入真人（审计带 schedule 原因）与返回 AI
    takeovers = audit.by_type("takeover")
    assert takeovers and "schedule:真人主推" in takeovers[0].payload["reason"]
    assert audit.count("rehandoff") == 1
    assert not brain.mixed.pending(10 ** 9), "排班应播放完毕"

    # 画面切换：交叉淡化过渡 + 真人帧流 + 切回数字人
    switches = [e["to"] for e in log if e["type"] == "switch_source"]
    assert switches == ["human", "avatar"]
    human_frames = [e for e in log if e["type"] == "human_frame"]
    assert len(human_frames) >= 3
    assert all(not e["badge_on"] for e in human_frames)   # 默认 ai_content_only
    assert any(e["type"] == "transition" for e in log)

    # 话术：AI 段正常回答；真人段弹幕被静默；返场注入的同类问题恢复回答
    assert "template_interact" in sources
    ai_phase_answers = [r for r in brain.speech_results
                        if "多少钱" in r.task.origin]
    assert ai_phase_answers, "返场注入的价格问题应被回答"
    human_phase_silenced = [r for r in brain.speech_results
                            if r.task.origin == "这个精华多少钱？"
                            and r.task.created_ts < takeovers[0].ts]
    assert not human_phase_silenced, "真人段内 AI 必须静默"
    assert not brain.pipeline.in_human_mode

    # 真人帧同样进入哈希审计链（画面源切换全程留痕）
    assert audit.count("visual_source") == 2
    assert audit.verify()[0]


def test_manual_takeover_switches_visual_with_capture():
    platform = MockPlatform("room-manual", human_capture=MockHumanCapture())
    brain = LiveBrain(platform=platform,
                      settings=Settings(clock_scale=0.0), room_id="room-manual")
    asyncio.run(brain.start())
    asyncio.run(brain._enter_human("ops_hotkey"))
    assert brain.pipeline.in_human_mode
    assert [e["to"] for e in brain.pipeline.log
            if e["type"] == "switch_source"] == ["human"]
    asyncio.run(brain._exit_human())
    assert not brain.pipeline.in_human_mode
    switches = [e["to"] for e in brain.pipeline.log
                if e["type"] == "switch_source"]
    assert switches == ["human", "avatar"]


def test_pending_speech_dropped_on_enter_human():
    from livebrain.util import uid
    from livebrain.decision.types import SpeechTask
    platform = MockPlatform("room-drop")
    brain = LiveBrain(platform=platform,
                      settings=Settings(clock_scale=0.0), room_id="room-drop")
    asyncio.run(brain.start())
    brain._pending_speech.append(SpeechTask(
        task_id=uid("spk"), track="template", sentences=["排队中的话术"],
        priority=4, origin="x"))
    asyncio.run(brain._enter_human("manual"))
    assert brain._pending_speech == []
    assert brain.audit.count("pending_dropped") == 1


def test_schedule_return_blocked_by_pending_promise():
    _HookBrain.submit_promise_on_human = True
    try:
        # 平台拒绝 ops -> 承诺无法核销，保持 pending
        platform = MockPlatform("room-blocked", human_capture=MockHumanCapture(),
                                ops_failure_rate=1.0)
        brain = _HookBrain(platform=platform, settings=_mixed_settings(),
                           room_id="room-blocked")
        # 交回被阻塞后保持真人画面（语义正确），测试侧限 tick 数避免长跑
        asyncio.run(brain.run_until_idle(max_ticks=120))
    finally:
        _HookBrain.submit_promise_on_human = False

    # 未核销承诺阻塞交回：保持真人画面并告警，不自动放行
    assert any(a.startswith("REHANDOFF_BLOCKED:pending_promises")
               for a in brain.alerts)
    assert brain.pipeline.in_human_mode
    assert brain.audit.count("rehandoff") == 0


def test_label_policy_always_overlays_human_frames():
    profile = ComplianceProfile(platform="mock", label_text="AI虚拟主播",
                                min_area_ratio=0.10, label_policy="always")
    platform = MockPlatform("room-label", compliance_profile=profile,
                            human_capture=MockHumanCapture())
    brain = LiveBrain(platform=platform,
                      settings=Settings(clock_scale=0.0), room_id="room-label")
    asyncio.run(brain.start())
    asyncio.run(brain._enter_human("manual"))
    for _ in range(3):
        asyncio.run(brain.pipeline.human_tick())
    human_frames = [e for e in brain.pipeline.log
                    if e["type"] == "human_frame"]
    assert human_frames and all(e["badge_on"] for e in human_frames)


def test_speak_rejected_in_human_mode():
    from livebrain.decision.types import SpeechTask
    from livebrain.util import uid
    platform = MockPlatform("room-reject", human_capture=MockHumanCapture())
    brain = LiveBrain(platform=platform,
                      settings=Settings(clock_scale=0.0), room_id="room-reject")
    asyncio.run(brain.start())
    asyncio.run(brain._enter_human("manual"))
    task = SpeechTask(task_id=uid("spk"), track="template",
                      sentences=["不该出现"], priority=2)
    try:
        asyncio.run(brain.pipeline.speak(task))
    except RuntimeError:
        pass
    else:
        raise AssertionError("真人画面段必须拒绝 AI 话术")
