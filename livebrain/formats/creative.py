"""AI 内容创作器（V4.4.1）：不指定内容时，AI 自己思考。

优先级：用户内容（--data，最高）> AI 原创 > 内置种子库兜底。

约束：
- 创作输出走与中轨一致的三道过滤（违禁词/极限词），但不走品类宣称
  （非商品话术）与数字填槽（段子里的"三公里"是修辞不是价格）；
- 复用中轨 LLM 降级链：失败/超时自动回落，直播不冷场；
- 版权白名单不可 AI 生成（音乐授权是法律约束，AI 不能替商家拿授权）。

审计：creative_generated / creative_fallback 入审计总线（创作占比可监控）。
"""
import asyncio
from typing import Callable, List, Optional

from ..execution.degradation import ProviderError
from .base import build_task

CREATIVE_PROMPTS = {
    "joke": (
        "你是直播间的单口相声演员，负责原创短段子。\n"
        "要求：两句结构——第一句铺垫，第二句抖包袱；口语化、节奏快；\n"
        "禁止：政治/宗教/疾病/性别等敏感话题、真实品牌名、广告法极限词、谐音梗。\n"
        "只输出这两句话，不要编号不要标题。"
    ),
    "topic": (
        "你是聊天陪伴主播，负责抛互动话题。\n"
        "要求：一句话，亲切口语化，观众能直接打在评论区接话；避免争议话题与极限词。\n"
        "只输出这一句话。"
    ),
    "crosstalk": (
        "你是相声演员，根据已有对词续写下一句台词。\n"
        "要求：紧接上文、一句台词；逗哏(A)负责推进抖包袱，捧哏(B)负责接话垫话；\n"
        "避免敏感话题与极限词。只输出这一句台词，不要角色前缀。"
    ),
}


class CreativeWriter:
    """场景包共用的 AI 创作入口：generate() 失败必回落（不抛给调用方）。"""

    def __init__(self, brain) -> None:
        self.brain = brain

    async def generate(self, kind: str, user_prompt: str,
                       sentences: int = 2) -> Optional[List[str]]:
        """生成并过滤；返回句子列表，失败返回 None（调用方走兜底）。"""
        from ..decision import filters           # 局部导入避免环
        from ..decision.llm_agent import split_sentences

        chain = self.brain.llm_chain
        settings = self.brain.settings
        provider = chain.acquire()
        if provider is None:
            self._audit("creative_fallback", kind, reason="all_providers_open")
            return None
        messages = [
            {"role": "system", "content": CREATIVE_PROMPTS[kind]},
            {"role": "user", "content": user_prompt},
        ]
        try:
            raw = await asyncio.wait_for(
                provider.chat(messages), timeout=settings.mid_budget_ms / 1000.0)
            chain.report_success(provider)
        except Exception:                       # 任何 provider 失败都回落，直播不冷场
            chain.report_failure(provider)
            self._audit("creative_fallback", kind, reason="provider_error")
            return None

        lines = [s for s in split_sentences(raw) if s.strip()]
        if not lines:
            self._audit("creative_fallback", kind, reason="empty_output")
            return None
        joined = "".join(lines)
        verdict = filters.check(joined)          # 三道过滤（无品类维度）
        if not verdict.passed:
            self._audit("creative_fallback", kind,
                        reason="filter:%s" % verdict.blocked)
            return None
        self._audit("creative_generated", kind, chars=len(joined))
        return lines[:max(1, sentences)]

    def _audit(self, event: str, kind: str, **extra) -> None:
        self.brain.audit.append(event, self.brain.room_id,
                                {"kind": kind, **extra})


def ai_task(brain, lines: List[str], source: str, origin: str,
            emotion: str = "witty") -> object:
    return build_task(lines, source=source, origin=origin, emotion=emotion,
                      clock=brain.clock)
