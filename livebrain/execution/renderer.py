"""渲染 Provider 接口与 Mock 实现（DESIGN §7.1/§7.4）。

打断协议（R13）：音频 50ms 淡出 + 200-300ms 中性表情交叉淡化过渡段，
杜绝口型穿帮。M2 在此文件追加 MuseTalk / SoulX Provider。
"""
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class VideoFrame:
    idx: int              # 全局帧号
    utterance_id: str
    scene: str            # talk / transition
    badge_on: bool        # AI 标识是否叠加（合规门禁的可观测面）
    ts: float


class RendererProvider:
    name = "renderer"

    async def render_sentence(self, utterance_id: str, text: str,
                              emotion: str, badge_on: bool) -> AsyncIterator[VideoFrame]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def transition(self, utterance_id: str) -> AsyncIterator[VideoFrame]:
        raise NotImplementedError
        yield  # pragma: no cover


class MockRenderer(RendererProvider):
    def __init__(self, name: str = "mock_renderer") -> None:
        self.name = name
        self._frame_idx = 0
        self._ts = 0.0

    def _next(self, utterance_id: str, scene: str, badge_on: bool) -> VideoFrame:
        self._frame_idx += 1
        self._ts += 0.04          # 25fps 模拟
        return VideoFrame(self._frame_idx, utterance_id, scene, badge_on, self._ts)

    async def render_sentence(self, utterance_id: str, text: str,
                              emotion: str, badge_on: bool) -> AsyncIterator[VideoFrame]:
        count = max(2, len(text) // 3)
        for _ in range(count):
            yield self._next(utterance_id, "talk", badge_on)

    async def transition(self, utterance_id: str) -> AsyncIterator[VideoFrame]:
        # 250ms 交叉淡化过渡（约 6 帧）
        for _ in range(6):
            yield self._next(utterance_id, "transition", True)
