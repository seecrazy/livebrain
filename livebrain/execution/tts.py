"""TTS Provider 接口、Mock 与 EdgeTTS 实现（DESIGN §7.1/§7.2）。

TTS 授权矩阵（R7）：
- 商用实时链路：火山/Azure/MiniMax 等有商用授权的流式 TTS（M2 起逐个接入）；
- EdgeTTSProvider 仅限验证期与预合成素材，不入商用降级链；
- MockTTS 用于测试与无网络环境。

edge_tts 为可选依赖（pip install edge-tts），未安装时构造成功、
调用抛 ProviderError，可正常进入降级链。
"""
from dataclasses import dataclass
from typing import AsyncIterator, Dict, Optional

from .degradation import ProviderError


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


class EdgeTTSProvider(TTSProvider):
    """验证期专用：edge-tts 神经语音（免费端点，禁商用实时链路）。

    style -> voice 映射可配置；未安装 edge_tts 时调用抛 ProviderError，
    由降级链切到下一家。预合成素材场景推荐离线批量生成 MP3 后走文件回放，
    而非运行时实时合成。
    """

    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
    STYLE_VOICES: Dict[str, str] = {
        "cheerful": "zh-CN-XiaoxiaoNeural",
        "steady": "zh-CN-XiaoyiNeural",
        "urgent": "zh-CN-YunxiNeural",
        "playful": "zh-CN-YunyangNeural",
        "calm": "zh-CN-YunxiNeural",
    }

    def __init__(self, name: str = "edge_tts",
                 default_voice: str = DEFAULT_VOICE,
                 style_voices: Optional[Dict[str, str]] = None) -> None:
        self.name = name
        self.default_voice = default_voice
        self.style_voices = dict(self.STYLE_VOICES)
        if style_voices:
            self.style_voices.update(style_voices)
        try:
            import edge_tts  # noqa: F401
            self._lib = edge_tts
        except ImportError:
            self._lib = None

    def voice_for(self, style: str) -> str:
        return self.style_voices.get(style, self.default_voice)

    async def synthesize(self, text: str, style: str) -> AsyncIterator[AudioChunk]:
        if self._lib is None:
            raise ProviderError("edge-tts 未安装（pip install edge-tts）")
        communicate = self._lib.Communicate(text, self.voice_for(style))
        seq = 0
        got_audio = False
        async for chunk in communicate.stream():
            if chunk.get("type") == "audio":
                seq += 1
                got_audio = True
                yield AudioChunk(seq, chunk.get("data", b""), is_last=False)
        if not got_audio:
            raise ProviderError("edge-tts 未返回音频（端点限流或文本为空）")
        yield AudioChunk(seq + 1, b"", is_last=True)
