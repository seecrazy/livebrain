"""filler 调度（DESIGN §6.2 慢轨 filler / M2 落地）：等待期衔接话术。

真实 LLM 延迟（MockLLM latency 模拟）下：filler 先上口垫住节奏，
正式回答到达后取代排队中的 filler / 打断正在播的 filler。
默认 emit_filler=False（Mock 零延迟场景无意义），E2E 行为不受影响。
"""
import asyncio

from livebrain.config import Settings
from livebrain.events import danmu_event, metric_event
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform


def test_filler_spoken_during_llm_latency_then_answer():
    settings = Settings(clock_scale=0.0, aggregate_window_s=0.4,
                        fast_reply_per_min=30, llm_reply_per_min=30,
                        breaker_threshold=3, emit_filler=True)
    brain = LiveBrain(platform=MockPlatform("room-filler"), settings=settings,
                      llm_script={"MOCK_PAIR": "这款含烟酰胺，敏感肌记得先局部试用哈～"},
                      llm_latency_s=0.12, room_id="room-filler")
    brain.schedule(0.1, metric_event("room-filler", 0.1, 120, 0.6))
    brain.schedule(0.1, metric_event("room-filler", 0.1, 120, 0.6))
    brain.schedule(0.1, danmu_event("room-filler", "u1", "MOCK_PAIR 敏感肌可以用吗", 0.2))
    brain.schedule(0.1, danmu_event("room-filler", "u2", "MOCK_PAIR 敏感肌可以用吗", 0.3))
    asyncio.run(brain.run_until_idle())

    sources = [r.task.source for r in brain.speech_results]
    assert "template_filler" in sources, "LLM 延迟期间应先播 filler"
    assert "mid_agent" in sources
    filler_idx = sources.index("template_filler")
    mid_idx = sources.index("mid_agent")
    assert filler_idx < mid_idx, "filler 必须先于正式回答"
    filler_text = brain.speech_results[filler_idx].spoken_text
    assert not any(ch.isdigit() for ch in filler_text), "filler 数字无关"


def test_filler_disabled_by_default():
    settings = Settings(clock_scale=0.0, aggregate_window_s=0.4,
                        fast_reply_per_min=30, llm_reply_per_min=30,
                        breaker_threshold=3)      # emit_filler 默认 False
    brain = LiveBrain(platform=MockPlatform("room-nf"), settings=settings,
                      llm_script={"MOCK_PAIR": "这款含烟酰胺哈～"},
                      llm_latency_s=0.12, room_id="room-nf")
    brain.schedule(0.1, metric_event("room-nf", 0.1, 120, 0.6))
    brain.schedule(0.1, metric_event("room-nf", 0.1, 120, 0.6))
    brain.schedule(0.1, danmu_event("room-nf", "u1", "MOCK_PAIR 敏感肌可以用吗", 0.2))
    brain.schedule(0.1, danmu_event("room-nf", "u2", "MOCK_PAIR 敏感肌可以用吗", 0.3))
    asyncio.run(brain.run_until_idle())
    sources = [r.task.source for r in brain.speech_results]
    assert "template_filler" not in sources
    assert "mid_agent" in sources
