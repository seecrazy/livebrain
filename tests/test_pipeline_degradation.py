"""流式管线与打断协议 + 降级链熔断 + 中轨超时兜底（DESIGN §6.2/§7.4/§7.5）。"""
import asyncio

from livebrain.config import Settings
from livebrain.data.audit import AuditLog
from livebrain.decision.llm_agent import MidTrackAgent, MockLLM
from livebrain.decision.fallback import FallbackSpeaker
from livebrain.decision.knowledge_store import KnowledgeStore, seed_default
from livebrain.decision.types import SpeechTask
from livebrain.execution.compliance import (ComplianceNotArmed,
                                            ComplianceOverlay)
from livebrain.execution.degradation import (CLOSED, OPEN, CapabilityChain,
                                             ProviderError)
from livebrain.execution.pipeline import StreamingPipeline
from livebrain.execution.renderer import MockRenderer
from livebrain.execution.tts import MockTTS
from livebrain.perception.aggregator import AggregatedQuestion
from tests.helpers import FakeClock


def _pipeline(armed=True):
    clock = FakeClock()
    compliance = ComplianceOverlay()
    if armed:
        from livebrain.platform.mock_platform import DEFAULT_PROFILE
        compliance.arm(DEFAULT_PROFILE)
    pipeline = StreamingPipeline(
        MockTTS(), MockRenderer(), compliance, clock, AuditLog(), "r1")
    return pipeline


def _long_task(sentences=None):
    return SpeechTask(
        task_id="t1", track="mid", sentences=sentences or ["第一句讲解", "第二句讲解", "第三句讲解"],
        priority=4, origin="测试")


def test_gate_blocks_when_not_armed():
    pipeline = _pipeline(armed=False)
    try:
        asyncio.run(pipeline.speak(_long_task()))
    except ComplianceNotArmed:
        assert any(e["type"] == "gate_blocked" for e in pipeline.log)
    else:
        raise AssertionError("未武装必须拒绝推流")


def test_speak_produces_audio_and_frames():
    pipeline = _pipeline()
    result = asyncio.run(pipeline.speak(_long_task()))
    assert result.sentences_spoken == 3 and not result.interrupted
    assert any(e["type"] == "audio" for e in pipeline.log)
    assert result.spoken_text == "第一句讲解第二句讲解第三句讲解"


def test_interrupt_fades_audio_and_transitions_video():
    pipeline = _pipeline()

    async def scenario():
        task = asyncio.ensure_future(pipeline.speak(_long_task()))
        await asyncio.sleep(0)          # 让第一句播出去
        pipeline.request_interrupt()
        return await task

    result = asyncio.run(scenario())
    assert result.interrupted
    assert result.sentences_spoken < 3
    fades = [e for e in pipeline.log if e["type"] == "audio_fade"]
    transitions = [e for e in pipeline.log if e["type"] == "transition"]
    assert fades and fades[0]["fade_ms"] == 50      # 50ms 音频淡出
    assert transitions                              # 250ms 视觉过渡段


# ---------------------------------------------------------------- 降级链
def _chain(providers, settings=None):
    settings = settings or Settings(breaker_threshold=2, breaker_cooldown_s=60)
    return CapabilityChain("llm", providers, settings, AuditLog(), FakeClock(), "r1")


class FailingLLM(MockLLM):
    def __init__(self, name):
        super().__init__(name, always_fail=True)


def test_breaker_opens_and_chain_switches():
    primary, backup = FailingLLM("p"), MockLLM("b")
    chain = _chain([primary, backup])
    assert chain.acquire().name == "p"
    chain.report_failure(primary)
    assert chain.breakers["p"].state() == CLOSED      # 阈值未到
    switch = chain.report_failure(primary)            # 第 2 次失败 -> 熔断
    assert switch and switch["to"] == "b"
    assert chain.breakers["p"].state() == OPEN
    assert chain.acquire().name == "b"                # 已切到备用


def test_all_open_returns_none():
    primary, backup = FailingLLM("p"), FailingLLM("b")
    chain = _chain([primary, backup])
    chain.report_failure(primary); chain.report_failure(primary)
    chain.report_failure(backup); chain.report_failure(backup)
    assert chain.acquire() is None


def test_chain_rollback():
    primary, backup = FailingLLM("p"), MockLLM("b")
    chain = _chain([primary, backup])
    chain.report_failure(primary); switch = chain.report_failure(primary)
    assert switch["to"] == "b"
    chain.rollback()
    assert chain.current_name() == "p"


# ---------------------------------------------------------------- 中轨兜底
def _agent(settings, providers):
    clock = FakeClock()
    knowledge = KnowledgeStore()
    seed_default(knowledge)
    chain = CapabilityChain("llm", providers, settings, AuditLog(), clock, "r1")
    agent = MidTrackAgent(settings, clock, knowledge, chain,
                          FallbackSpeaker(), AuditLog(), "r1")
    return agent


def _consult():
    return AggregatedQuestion(
        intent="product_consult", subtype="敏感", topic_key="consult:敏感",
        representative_text="敏感肌能用吗", count=1, user_ids=["u1"])


def _product():
    from livebrain.data.product_store import ProductStore
    from livebrain.data.product_store import seed_default
    store = ProductStore()
    seed_default(store, 0.0)
    return store.get("SKU001")


class PersonaStub:
    def mid_track_fragment(self):
        return "你是测试主播"


class StrategyStub:
    emotion = "steady"
    name = "explain"


def test_mid_track_success_path():
    settings = Settings()
    ok_llm = MockLLM("ok", script={"敏感": "敏感肌可以先在耳后局部试用哈～"})
    agent = _agent(settings, [ok_llm])
    task = asyncio.run(agent.generate(_consult(), _product(), PersonaStub(),
                                      StrategyStub(), online=88))
    assert task.track == "mid"
    assert "局部试用" in task.sentences[0]


def test_mid_track_timeout_falls_back():
    settings = Settings(mid_budget_ms=30)
    slow = MockLLM("slow", latency_s=0.2)
    agent = _agent(settings, [slow])
    task = asyncio.run(agent.generate(_consult(), _product(), PersonaStub(),
                                      StrategyStub()))
    assert task.track == "fallback" and task.source == "fallback_pool"


def test_mid_track_provider_error_falls_back():
    settings = Settings(breaker_threshold=1)   # 一次失败即熔断 -> 立即换备用
    bad, good = FailingLLM("bad"), MockLLM("good")
    agent = _agent(settings, [bad, good])
    task = asyncio.run(agent.generate(_consult(), _product(), PersonaStub(),
                                      StrategyStub()))
    # 第一次失败换备用 provider 成功
    assert task.track == "mid"


def test_mid_track_all_open_falls_back():
    settings = Settings(breaker_threshold=1)
    bad1, bad2 = FailingLLM("bad1"), FailingLLM("bad2")
    agent = _agent(settings, [bad1, bad2])
    task = asyncio.run(agent.generate(_consult(), _product(), PersonaStub(),
                                      StrategyStub()))
    assert task.track == "fallback"


def test_hallucinated_digits_never_spoken():
    settings = Settings()
    liar = MockLLM("liar", script={"敏感": "这款只要199元，敏感肌可用！"})
    agent = _agent(settings, [liar])
    task = asyncio.run(agent.generate(_consult(), _product(), PersonaStub(),
                                      StrategyStub()))
    joined = "".join(task.sentences)
    assert "199" not in joined
    assert task.track == "fallback"   # 两次校验失败 -> 兜底
