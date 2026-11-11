"""LLM 中轨代理（DESIGN §6.3/§6.7）：RAG + 填槽 + 事实回检 + 超时兜底。

流程：检索 -> LLM 生成（只允许占位符）-> 占位校验（重试 1 次）
     -> 事实回检（丢弃无检索支持的宣称句）-> 过滤 -> 交给编排器做原子展开与人设装饰。
全链熔断/超时/校验失败 -> 兜底话术池。失败与拦截全部进审计（幻觉率监控数据点）。
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from ..config import Settings
from ..data.product_store import Product
from ..execution.degradation import CapabilityChain, ProviderError
from ..perception.aggregator import AggregatedQuestion
from . import filters, slots
from .fallback import FallbackSpeaker
from .field_controller import StageStrategy
from .knowledge_store import KnowledgeStore, Snippet
from .persona import PersonaManager
from .types import PRIORITY_MID, SpeechTask, TRACK_MID
from ..util import uid

# 宣称性关键词：命中则该句需要检索片段支持
CLAIM_KEYWORDS = ["含有", "成分", "适合", "可以", "能够", "不含", "无添加", "主打", "建议"]

IRON_RULES = (
    "回答观众问题时必须遵守铁律：\n"
    "1. 涉及价格、库存、优惠、发货时效等数字，只能使用占位符 "
    "{price} {orig_price} {coupon} {stock} {ship_days} {online}，"
    "禁止输出任何阿拉伯数字。\n"
    "2. 禁止任何承诺性表述（保证、承诺、秒发、假一赔十、无效退款），不替商家做保证。\n"
    "3. 功效与医疗相关表述只依据下方资料；资料没有的一律说\"具体以商品详情页为准\"，"
    "禁止宣称治疗、治愈、降血糖等功效。\n"
    "4. 语气口语化亲切，一到三句话，不用列表和标题。\n"
)


class LLMProvider:
    name = "llm"

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError


class MockLLM(LLMProvider):
    """脚本化 Mock：按用户消息中的标记返回预设响应。

    响应 "$FAIL" 表示模拟该场景 provider 报错；latency_s 模拟真实网络延迟
    （不走 Clock，便于测试超时预算）。
    """

    def __init__(self, name: str, script: Optional[Dict[str, str]] = None,
                 default: str = "这款可以先在耳后局部试用哈，具体以商品详情页为准～",
                 latency_s: float = 0.0, always_fail: bool = False) -> None:
        self.name = name
        self.script = script or {}
        self.default = default
        self.latency_s = latency_s
        self.always_fail = always_fail
        self.seen_messages: List[Dict[str, str]] = []

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        self.seen_messages.append(messages[-1])
        if self.always_fail:
            raise ProviderError(self.name)
        if self.latency_s:
            await asyncio.sleep(self.latency_s)
        user = ""
        for m in messages:
            if m["role"] == "user":
                user = m["content"]
        for marker, response in self.script.items():
            if marker in user:
                if response == "$FAIL":
                    raise ProviderError("scripted_fail:" + marker)
                return response
        return self.default


_SENTENCE_SPLIT = "。！？!?~～\n"


def split_sentences(text: str) -> List[str]:
    sentences, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _SENTENCE_SPLIT:
            sentence = buf.strip()
            if sentence:
                sentences.append(sentence)
            buf = ""
    tail = buf.strip()
    if tail:
        sentences.append(tail)
    return sentences


class MidTrackAgent:
    def __init__(self, settings: Settings, clock, knowledge: KnowledgeStore,
                 chain: CapabilityChain, fallback: FallbackSpeaker,
                 audit, room_id: str = "") -> None:
        self.settings = settings
        self.clock = clock
        self.knowledge = knowledge
        self.chain = chain
        self.fallback = fallback
        self.audit = audit
        self.room_id = room_id

    def _messages(self, question: AggregatedQuestion, product: Product,
                  snippets: List[Snippet], persona: PersonaManager) -> List[Dict[str, str]]:
        material = "\n".join("- " + s.text for s in snippets) or "- （无资料，请以详情页为准作答）"
        system = persona.mid_track_fragment() + "\n\n" + IRON_RULES
        user = ("商品：{name}（品类：{category}）\n资料：\n{material}\n\n"
                "观众问题：{q}").format(
            name=product.name, category=product.category,
            material=material, q=question.representative_text)
        return [{"role": "system", "content": system},
                {"role": "user", "content": user}]

    async def generate(self, question: AggregatedQuestion, product: Product,
                       persona: PersonaManager, strategy: StageStrategy,
                       online: int = 0) -> SpeechTask:
        snippets = self.knowledge.retrieve(question.representative_text, product.sku)
        messages = self._messages(question, product, snippets, persona)
        budget_s = self.settings.mid_budget_ms / 1000.0

        raw: Optional[str] = None
        for _attempt in range(2):
            provider = self.chain.acquire()
            if provider is None:
                self.audit.append("generation_rejected", self.room_id,
                                  {"reason": "all_providers_open",
                                   "origin": question.representative_text})
                break
            try:
                raw = await asyncio.wait_for(provider.chat(messages),
                                             timeout=budget_s)
                self.chain.report_success(provider)
            except asyncio.TimeoutError:
                self.chain.report_failure(provider)
                self.audit.append("generation_rejected", self.room_id,
                                  {"reason": "timeout",
                                   "provider": provider.name})
                raw = None
                continue
            except ProviderError as exc:
                self.chain.report_failure(provider)
                self.audit.append("generation_rejected", self.room_id,
                                  {"reason": "provider_error",
                                   "provider": provider.name,
                                   "error": str(exc)})
                raw = None
                continue
            validation = slots.validate_generated(raw)
            if not validation.ok:
                self.audit.append("generation_rejected", self.room_id,
                                  {"reason": "slot_validation",
                                   "problems": validation.problems,
                                   "raw": raw})
                raw = None
                continue
            break

        if raw is None:
            return self.fallback.next(product.name, online, strategy,
                                      origin=question.representative_text,
                                      clock=self.clock)

        kept, dropped = self._backcheck(raw, product.sku, snippets)
        for sentence in dropped:
            self.audit.append("backcheck_drop", self.room_id,
                              {"sentence": sentence,
                               "origin": question.representative_text})
        if not kept:
            return self.fallback.next(product.name, online, strategy,
                                      origin=question.representative_text,
                                      clock=self.clock)

        joined = "".join(kept)
        verdict = filters.check(joined, product.category, product.qual_flags)
        if not verdict.passed:
            self.audit.append("filter_block", self.room_id,
                              {"blocked": verdict.blocked, "text": joined})
            return self.fallback.next(product.name, online, strategy,
                                      origin=question.representative_text,
                                      clock=self.clock)

        facts = {"product_name": product.name, "online": str(online)}
        final: List[str] = []
        for sentence in kept:
            filled, unfilled = slots.fill(sentence, facts)
            if filled is None or slots.extract_slots(filled):
                return self.fallback.next(product.name, online, strategy,
                                          origin=question.representative_text,
                                          clock=self.clock)
            final.append(filled)

        return SpeechTask(
            task_id=uid("spk"), track=TRACK_MID, sentences=final,
            priority=PRIORITY_MID, emotion=strategy.emotion, ops=[],
            origin=question.representative_text, source="mid_agent",
            facts=facts, created_ts=self.clock.now())

    def _backcheck(self, raw: str, sku: str,
                   snippets: List[Snippet]) -> Tuple[List[str], List[str]]:
        """事实回检：含宣称关键词的句子必须有检索片段关键词支持。"""
        universe = self.knowledge.keyword_universe(sku)
        kept: List[str] = []
        dropped: List[str] = []
        for sentence in split_sentences(raw):
            if not any(k in sentence for k in CLAIM_KEYWORDS):
                kept.append(sentence)
                continue
            words_in_sentence = [w for w in universe if w in sentence]
            supported = any((w in snippet.text)
                            for w in words_in_sentence for snippet in snippets)
            if words_in_sentence and supported:
                kept.append(sentence)
            else:
                dropped.append(sentence)
        return kept, dropped
