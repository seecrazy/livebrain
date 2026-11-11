"""兜底话术池（DESIGN §6.10）：LLM 全链熔断时的大话术池。

防"短周期机械重复"（平台反录播规则）：
- 每品多模板乱序轮播，不连续重复；
- 通过占位符注入实时元素（在线人数），即使同一模板每次内容也不同。
"""
import random
from typing import Dict, List, Optional

from ..util import uid
from . import slots
from .field_controller import StageStrategy
from .types import PRIORITY_MID, SpeechTask, TRACK_FALLBACK

_POOL: List[str] = [
    "{product_name}这款我们主打的就是性价比，详情页说得明明白白，喜欢的宝宝先加购～",
    "刚进来的宝宝看下 {product_name}，有不懂的随时问，我看到都会说～",
    "现在 {online} 位宝宝在线，{product_name} 链接就在下方小黄车，去哪拍我再说一遍哈～",
    "{product_name} 怎么选、适不适合，一句话说不完，宝宝们看详情页的说明图，很清楚～",
    "老粉都知道我们家节奏，{product_name} 今天价格给到位了，犹豫的宝宝先领券加购～",
    "有宝宝问效果，我不敢乱说，{product_name} 的成分和用法详情页都有，看完再拍不亏～",
]


class FallbackSpeaker:
    def __init__(self) -> None:
        self._order: List[int] = []
        self._pos = 0
        self._recent: List[int] = []

    def _next_index(self) -> int:
        if not self._order:
            self._order = list(range(len(_POOL)))
            random.shuffle(self._order)
            self._pos = 0
        index = self._order[self._pos]
        self._pos += 1
        if self._pos >= len(self._order):
            self._order = []
        return index

    def next(self, product_name: str, online: int, strategy: StageStrategy,
             origin: str = "", clock=None,
             facts: Optional[Dict[str, str]] = None) -> SpeechTask:
        # 避免与最近 2 次重复
        for _ in range(4):
            index = self._next_index()
            if index not in self._recent:
                break
        self._recent.append(index)
        if len(self._recent) > 2:
            self._recent = self._recent[-2:]

        template = _POOL[index]
        all_facts = {"product_name": product_name, "online": str(online)}
        if facts:
            all_facts.update(facts)
        text, unfilled = slots.fill(template, all_facts)
        if text is None:  # 理论不可达：兜底模板只用 product_name/online
            text = "宝宝们稍等哈，马上继续讲～"
        now = clock.now() if clock else 0.0
        return SpeechTask(
            task_id=uid("spk"), track=TRACK_FALLBACK, sentences=[text],
            priority=PRIORITY_MID, emotion=strategy.emotion, ops=[],
            origin=origin, source="fallback_pool",
            facts=all_facts, created_ts=now)
