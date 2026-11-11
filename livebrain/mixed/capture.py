"""真人采集通道（DESIGN §7.7）：摄像头帧 / 麦克风。

M1 提供 Mock 实现；M3 实装接 OpenCV/采集卡/NDI 等。
Mock 按真实硬件节奏出帧（25fps，真实 sleep 不走 Clock 缩放），
保证排班边界的真实时间语义与编排器心跳正确。
生产注意：真人画面属采集内容而非 AI 生成，AI 标识按 label_policy
（ai_content_only / always）决定是否叠加（见 execution/compliance.py）。
"""
import asyncio
from dataclasses import dataclass
from typing import Optional


@dataclass
class CaptureFrame:
    seq: int
    ts: float
    scene: str = "human_talk"      # human_talk / human_idle / human_guest


class HumanCapture:
    name = "human_capture"

    async def next_frame(self) -> Optional[CaptureFrame]:
        raise NotImplementedError


class MockHumanCapture(HumanCapture):
    """确定性真人帧流：25fps 真实节奏，场景随序号轮换。"""

    FRAME_INTERVAL = 0.04          # 25fps，模拟采集硬件节拍

    def __init__(self, name: str = "mock_capture") -> None:
        self.name = name
        self._seq = 0
        self._ts = 0.0
        self.frames_sent = 0

    async def next_frame(self) -> CaptureFrame:
        await asyncio.sleep(self.FRAME_INTERVAL)   # 真实节奏，不缩放
        self._seq += 1
        self._ts += self.FRAME_INTERVAL
        self.frames_sent += 1
        scene = "human_talk" if self._seq % 4 else "human_idle"
        return CaptureFrame(self._seq, self._ts, scene)
