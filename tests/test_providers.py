"""M2 真实 Provider 单元测试：OpenAI 兼容 LLM + EdgeTTS。

全部离线：transport 注入 / 模块缺失注入，不发真实网络请求。
"""
import asyncio
import importlib
import sys
import types

from livebrain.execution.degradation import ProviderError
from livebrain.execution.llm_openai_compat import OpenAICompatProvider
from livebrain.execution.tts import AudioChunk, EdgeTTSProvider


def _ok_transport(url, headers, body, timeout):
    assert body["model"] == "ep-test"
    assert headers["Authorization"].startswith("Bearer ")
    assert url.endswith("/chat/completions")
    return {"choices": [{"message": {"content": "敏感肌可以先局部试用哈～"}}]}


def test_openai_compat_success_and_endpoint_join():
    provider = OpenAICompatProvider(
        name="ark", base_url="https://example.com/api/v3",
        api_key="sk-x", model="ep-test", transport=_ok_transport)
    result = asyncio.run(provider.chat(
        [{"role": "user", "content": "敏感肌能用吗"}]))
    assert result == "敏感肌可以先局部试用哈～"
    assert provider.seen_messages[0]["role"] == "user"


def test_openai_compat_endpoint_not_duplicated():
    provider = OpenAICompatProvider(
        name="ark", base_url="https://example.com/v1/chat/completions",
        api_key="k", model="m", transport=lambda *a: {})
    assert provider._endpoint().count("/chat/completions") == 1


def test_openai_compat_http_error_maps_to_provider_error():
    import urllib.error

    def _http_error_transport(url, headers, body, timeout):
        raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)

    provider = OpenAICompatProvider(
        name="ark", base_url="https://e.com", api_key="k", model="m",
        transport=_http_error_transport)
    try:
        asyncio.run(provider.chat([{"role": "user", "content": "x"}]))
    except ProviderError as exc:
        assert "429" in str(exc)
    else:
        raise AssertionError("HTTP 错误必须映射为 ProviderError 交给熔断器")


def test_openai_compat_bad_payload_maps_to_provider_error():
    provider = OpenAICompatProvider(
        name="ark", base_url="https://e.com", api_key="k", model="m",
        transport=lambda *a: {"unexpected": True})
    try:
        asyncio.run(provider.chat([{"role": "user", "content": "x"}]))
    except ProviderError:
        pass
    else:
        raise AssertionError("异常响应结构必须映射为 ProviderError")


def test_openai_compat_misconfigured_raises_on_call():
    provider = OpenAICompatProvider(name="blank")   # 无 base_url/model
    try:
        asyncio.run(provider.chat([{"role": "user", "content": "x"}]))
    except ProviderError as exc:
        assert "未配置" in str(exc)
    else:
        raise AssertionError("未配置必须调用期报错（可入降级链）")


# ---------------------------------------------------------------- EdgeTTS
def test_edge_tts_voice_mapping():
    provider = EdgeTTSProvider()
    assert provider.voice_for("cheerful") == "zh-CN-XiaoxiaoNeural"
    assert provider.voice_for("urgent") == "zh-CN-YunxiNeural"
    assert provider.voice_for("unknown-style") == provider.default_voice


def test_edge_tts_missing_lib_raises_provider_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", None)   # 触发 ImportError
    provider = EdgeTTSProvider()

    async def consume():
        async for _chunk in provider.synthesize("你好", "cheerful"):
            pass

    try:
        asyncio.run(consume())
    except ProviderError as exc:
        assert "edge-tts" in str(exc)
    else:
        raise AssertionError("未安装 edge-tts 必须抛 ProviderError 走降级链")


def test_edge_tts_installed_env_constructs():
    """本机已装 edge_tts 7.3.1：构造成功且 lib 可用（不发起网络请求）。"""
    provider = EdgeTTSProvider()
    assert provider._lib is not None


def test_audio_chunk_shape():
    chunk = AudioChunk(seq=1, data=b"x", is_last=True, fade_ms=50)
    assert chunk.fade_ms == 50 and chunk.is_last
