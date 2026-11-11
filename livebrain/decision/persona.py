"""人设与情绪管理（DESIGN §6.9）。

persona = prompt 片段 + TTS style + 表情基线 + 口头禅。
约束：手动切换单场 <=3 次；自动切换仅阶段边界。
装饰器（口头禅）必须数字无关，不破坏填槽校验。
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from ..config import Settings


@dataclass
class Persona:
    persona_id: str
    name: str
    prompt_fragment: str
    tts_style: str
    emotion_baseline: str
    catchphrase: str


PERSONAS: Dict[str, Persona] = {
    "xiaotian": Persona(
        "xiaotian", "小甜",
        "你是活泼亲切的带货主播小甜，语气热情，称呼观众\"宝宝\"，句子口语化、节奏轻快。",
        "cheerful_young_female", "cheerful", "宝宝们"),
    "ajing": Persona(
        "ajing", "阿静",
        "你是专业沉稳的主播阿静，讲解条理清楚，语速平缓，称呼观众\"朋友们\"，重点讲成分与适用性。",
        "professional_female", "calm", "朋友们"),
}


class PersonaManager:
    def __init__(self, settings: Settings,
                 initial: str = "xiaotian") -> None:
        self.settings = settings
        self.current: Persona = PERSONAS[initial]
        self.manual_switches = 0
        self._utterance_seq = 0

    def switch(self, persona_id: str, source: str,
               stage_boundary: bool = False) -> Tuple[bool, str]:
        if persona_id not in PERSONAS:
            return False, "unknown_persona"
        if persona_id == self.current.persona_id:
            return True, "already"
        if source == "manual":
            if self.manual_switches >= self.settings.manual_persona_switch_limit:
                return False, "manual_limit_reached"
            self.manual_switches += 1
        elif source == "auto" and not stage_boundary:
            return False, "auto_requires_stage_boundary"
        self.current = PERSONAS[persona_id]
        return True, "ok"

    def decorate(self, text: str) -> str:
        """口头禅装饰：每 3 句追加一次，数字无关，不重复叠加。"""
        self._utterance_seq += 1
        catch = self.current.catchphrase
        if self._utterance_seq % 3 != 0 or catch in text:
            return text
        if text.endswith(("？", "～", "！", "。", "哈")):
            return text
        return text + "，" + catch + "～"

    def mid_track_fragment(self) -> str:
        """注入中轨 LLM system prompt 的人设片段。"""
        return self.current.prompt_fragment
