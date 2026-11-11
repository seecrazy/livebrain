"""TTS Provider 接口与 Mock 实现（DESIGN §7.1/§7.2）。

商用链只用有商用授权的流式 TTS（火山/Azure/MiniMax）；
Edge TTS 仅限验证期与预合成素材，不入商用降级链（R7）。
M2 在此文件追加 ArkTTS / AzureTTS Provider。
"""
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class AudioChunk:
    seq: int
    data: bytes
    is_last: bool
    fade_ms: int = 0


class TTSProvider:
    name = "tts"

    async def synthesize(self, text: str, style: str) -> AsyncIterator[AudioChunk]:
        raise NotImplementedError
        yield  # pragma: no cover


class MockTTS(TTSProvider):
    def __init__(self, name: str = "mock_tts") -> None:
        self.name = name
        self.calls: list = []

    async def synthesize(self, text: str, style: str) -> AsyncIterator[AudioChunk]:
        self.calls.append({"text": text, "style": style})
        yield AudioChunk(1, ("tts-head:%s" % style).encode("utf-8")[:32], False)
        yield AudioChunk(2, b"tts-tail", True)
