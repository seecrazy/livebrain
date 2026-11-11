"""知识库（DESIGN §8.2）：卖点/FAQ/售后，检索增强与事实回检的依据。

M1 关键词打分实现；接口按 pgvector 设计，M2 平移。
健康度：未回复问题清单 + 回检拦截清单驱动运营每日补充。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class KnowledgeDoc:
    doc_id: str
    sku: str
    text: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class Snippet:
    doc_id: str
    sku: str
    text: str
    score: float

    def contains_any(self, words: List[str]) -> bool:
        return any(w in self.text for w in words)


class KnowledgeStore:
    def __init__(self) -> None:
        self._docs: List[KnowledgeDoc] = []

    def add(self, doc: KnowledgeDoc) -> None:
        self._docs.append(doc)

    def retrieve(self, query: str, sku: str, k: int = 3) -> List[Snippet]:
        scored: List[Snippet] = []
        for doc in self._docs:
            if doc.sku and doc.sku != sku:
                continue
            score = sum(1.0 for kw in doc.keywords if kw in query)
            if score > 0:
                scored.append(Snippet(doc.doc_id, doc.sku, doc.text, score))
        scored.sort(key=lambda s: -s.score)
        return scored[:k]

    def keyword_universe(self, sku: Optional[str] = None) -> Set[str]:
        """回检用的词汇表：全部（或指定商品）文档关键词。"""
        universe: Set[str] = set()
        for doc in self._docs:
            if sku and doc.sku and doc.sku != sku:
                continue
            universe.update(doc.keywords)
        return universe


def seed_default(store: KnowledgeStore) -> None:
    docs = [
        KnowledgeDoc("kd-1", "SKU001",
                     "含 5% 烟酰胺，主打提亮肤色与保湿；敏感肌建议先在耳后局部试用，无不适再上脸。",
                     ["烟酰胺", "提亮", "保湿", "敏感肌", "局部试用"]),
        KnowledgeDoc("kd-2", "SKU001",
                     "建议晚间洁面后使用，白天使用需配合防晒；孕期哺乳期不建议使用。",
                     ["晚间", "防晒", "孕期", "哺乳期"]),
        KnowledgeDoc("kd-3", "SKU002",
                     "每粒含叶黄素酯，是普通食品不是保健品，不能宣称任何功效；儿童每日不超过两粒。",
                     ["叶黄素酯", "普通食品", "儿童"]),
        KnowledgeDoc("kd-4", "",
                     "售后政策：支持七天无理由退货，未拆封商品退运费由商家承担。",
                     ["七天无理由", "退货", "售后"]),
    ]
    for doc in docs:
        store.add(doc)
