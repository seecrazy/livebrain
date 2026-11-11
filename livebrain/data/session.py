"""会话状态（DESIGN §8.x 数据层）：当前品/在线人数/话术计数等轻状态。

M1 内存实现；M2 平移 Redis（TTL + 长度控制）。
"""
from dataclasses import dataclass, field
from typing import Deque, Optional
from collections import deque


@dataclass
class SessionState:
    room_id: str
    current_sku: str
    online: int = 0
    stage: str = "warmup"
    persona_id: str = "xiaotian"
    started_ts: float = 0.0
    utterance_count: int = 0
    last_questions: Deque[str] = field(default_factory=lambda: deque(maxlen=20))

    def note_question(self, text: str) -> None:
        self.last_questions.append(text)

    def note_utterance(self) -> None:
        self.utterance_count += 1
