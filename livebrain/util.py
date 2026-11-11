"""通用工具：可缩放时钟、规范化 JSON、哈希、ID 生成。"""
import asyncio
import hashlib
import itertools
import json
import time
from typing import Any, Dict


def canonical_json(obj: Any) -> str:
    """规范化序列化：键排序+紧凑分隔，保证哈希输入确定。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pii(identifier: str) -> str:
    """PII 最小化：持久化载荷中的用户标识以哈希留存（控制台实时视图保留原文）。"""
    return "u_" + sha256_hex(str(identifier))[:10]


_uid_counter = itertools.count(1)


def uid(prefix: str = "") -> str:
    return "%s%d-%s" % (prefix, next(_uid_counter), sha256_hex(str(time.time()))[:6])


class Clock:
    """可缩放时钟：now() 返回真实墙钟（审计需要真实时间戳），sleep 按比例缩放。

    scale=1.0 正常实时；demo 用 0.05；测试用 0（立即让出，不真实睡眠）。
    注意：外部 IO（如 LLM Provider 模拟延迟）不走 Clock，用真实 sleep，
    这样测试里也能验证超时预算逻辑。
    """

    def __init__(self, scale: float = 1.0) -> None:
        self.scale = max(0.0, scale)

    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        if self.scale <= 0:
            await asyncio.sleep(0)
            return
        await asyncio.sleep(seconds * self.scale)
