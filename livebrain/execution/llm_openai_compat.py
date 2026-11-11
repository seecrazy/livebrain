"""OpenAI 兼容端点的真实 LLM Provider（M2）。

零第三方依赖：urllib + run_in_executor。适用于一切 /chat/completions
兼容服务（火山方舟 Ark、DeepSeek、vLLM 自托管等）。

用法（Ark 示例）：
    provider = OpenAICompatProvider(
        name="ark",
        base_url="https://ark.cn-beijing.volcengine.com/api/v3",
        model="ep-2026xxxx",            # 方舟接入点 ID 或模型名
        api_key=os.environ["ARK_API_KEY"])

凭据顺序：显式参数 > LIVEBRAIN_LLM_API_KEY > ARK_API_KEY。
transport 参数仅供测试注入，生产走 urllib。
"""
import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional

from .degradation import ProviderError


def _urllib_post(url: str, headers: Dict[str, str], body: Dict,
                 timeout: float) -> Dict:
    """同步 HTTP POST（在线程池中执行），返回解析后的 JSON。"""
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers,
        method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class OpenAICompatProvider:
    """LLMProvider 接口的 OpenAI 兼容实现（接口见 decision.llm_agent）。"""

    name = "openai_compat"

    def __init__(self, name: str = "openai_compat",
                 base_url: str = "",
                 api_key: Optional[str] = None,
                 model: str = "",
                 timeout_s: float = 15.0,
                 temperature: float = 0.7,
                 transport: Optional[Callable] = None) -> None:
        self.name = name
        self.base_url = (base_url or os.environ.get("LIVEBRAIN_LLM_BASE_URL", "")
                         ).rstrip("/")
        self.api_key = (api_key or os.environ.get("LIVEBRAIN_LLM_API_KEY")
                        or os.environ.get("ARK_API_KEY") or "")
        self.model = model or os.environ.get("LIVEBRAIN_LLM_MODEL", "")
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.transport = transport or _urllib_post
        if not self.base_url or not self.model:
            # 构造不抛错（降级链要求可实例化），调用时统一报 ProviderError
            self._misconfigured = True
        else:
            self._misconfigured = False
        self.seen_messages: List[Dict[str, str]] = []

    def _endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return self.base_url + "/chat/completions"

    async def chat(self, messages: List[Dict[str, str]]) -> str:
        self.seen_messages.append(messages[-1])
        if self._misconfigured:
            raise ProviderError("%s: base_url/model 未配置" % self.name)
        body = {"model": self.model, "messages": messages,
                "temperature": self.temperature}
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer %s" % self.api_key}
        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(
                None, self.transport, self._endpoint(), headers, body,
                self.timeout_s)
        except urllib.error.HTTPError as exc:
            raise ProviderError("%s: HTTP %s" % (self.name, exc.code))
        except urllib.error.URLError as exc:
            raise ProviderError("%s: network %s" % (self.name, exc.reason))
        except Exception as exc:            # 解析错误等，统一交给熔断器
            raise ProviderError("%s: %s" % (self.name, exc))
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("%s: 响应结构异常 %s" % (self.name, exc))
