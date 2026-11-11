"""流式管线（DESIGN §7.4）：切句 -> TTS -> 渲染 -> AI标识 -> 帧哈希 -> 推流。

打断协议（R13，P0 级功能）：
- request_interrupt() 置位；当前句播完边界处生效（不打断半句，保证口型完整）；
- 当前音频 50ms 淡出 -> 渲染层 250ms 中性表情交叉淡化过渡 -> 新话术接入。

合规门禁（R/§7.3）：标识未武装时 speak() 直接抛 ComplianceNotArmed，
不产出任何可推流帧。

帧级追溯（§8.4）：每 30 帧一个检查点哈希入审计链；话术结束写 utterance
审计条目（全文/轨道/来源/是否被打断/帧区间哈希）。
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..decision.types import SpeechTask
from ..events import LiveEvent
from ..util import sha256_hex, uid
from .compliance import ComplianceNotArmed, ComplianceOverlay
from .renderer import RendererProvider
from .tts import TTSProvider

GENESIS_FRAME = sha256_hex("livebrain-frame-genesis")


@dataclass
class SpeechResult:
    utterance_id: str
    task: SpeechTask
    sentences_spoken: int
    interrupted: bool
    frame_checkpoints: List[str] = field(default_factory=list)
    last_frame_hash: str = ""
    judgment_events: List[LiveEvent] = field(default_factory=list)

    @property
    def spoken_text(self) -> str:
        return "".join(self.task.sentences[:self.sentences_spoken])


class StreamingPipeline:
    def __init__(self, tts: TTSProvider, renderer: RendererProvider,
                 compliance: ComplianceOverlay, clock, audit, room_id: str,
                 platform=None,
                 speech_sink: Optional[Callable[[str, str], None]] = None) -> None:
        self.tts = tts
        self.renderer = renderer
        self.compliance = compliance
        self.clock = clock
        self.audit = audit
        self.room_id = room_id
        self.platform = platform
        self.speech_sink = speech_sink
        # 观测日志（测试与 demo 断言用）
        self.log: List[Dict[str, Any]] = []
        self.busy = False
        self.current_task: Optional[SpeechTask] = None
        self._interrupt = False
        self._frame_hash = GENESIS_FRAME
        self._frame_count = 0

    def request_interrupt(self) -> None:
        self._interrupt = True

    async def speak(self, task: SpeechTask) -> SpeechResult:
        if not self.compliance.armed:
            self.log.append({"type": "gate_blocked", "task_id": task.task_id})
            raise ComplianceNotArmed("AI 标识未武装，拒绝推流")

        self.busy = True
        self.current_task = task
        self._interrupt = False
        utterance_id = uid("utt")
        checkpoints: List[str] = []
        spoken = 0
        interrupted = False
        try:
            for index, sentence in enumerate(task.sentences):
                if self._interrupt:
                    interrupted = True
                    self.log.append({"type": "audio_fade", "utterance_id": utterance_id,
                                     "fade_ms": 50, "at_sentence": index})
                    async for frame in self.renderer.transition(utterance_id):
                        checkpoint = self._record_frame(frame)
                        if checkpoint:
                            checkpoints.append(checkpoint)
                    self.log.append({"type": "transition", "utterance_id": utterance_id,
                                     "frames": 6})
                    break

                chunks = []
                async for chunk in self.tts.synthesize(sentence, task.emotion):
                    chunks.append(chunk)
                self.log.append({"type": "audio", "utterance_id": utterance_id,
                                 "sentence": index, "chunks": len(chunks)})
                if self.speech_sink:
                    self.speech_sink(utterance_id, sentence)

                async for frame in self.renderer.render_sentence(
                        utterance_id, sentence, task.emotion, badge_on=True):
                    checkpoint = self._record_frame(frame)
                    if checkpoint:
                        checkpoints.append(checkpoint)
                spoken = index + 1
                await self.clock.sleep(0.01)   # 句间让出控制点，模拟帧时间

            result = SpeechResult(
                utterance_id=utterance_id, task=task,
                sentences_spoken=spoken, interrupted=interrupted,
                frame_checkpoints=checkpoints,
                last_frame_hash=self._frame_hash)

            self.audit.append("utterance", self.room_id, {
                "utterance_id": utterance_id,
                "task_id": task.task_id,
                "track": task.track,
                "source": task.source,
                "emotion": task.emotion,
                "origin": task.origin,
                "text": "".join(task.sentences[:max(spoken, 0)]),
                "interrupted": interrupted,
                "sentences_planned": len(task.sentences),
                "sentences_spoken": spoken,
                "frame_checkpoints": checkpoints,
                "last_frame_hash": self._frame_hash,
            })

            if self.platform is not None:
                try:
                    result.judgment_events = await self.platform.push_speech(
                        utterance_id, "".join(task.sentences),
                        {"track": task.track, "source": task.source})
                except Exception:
                    result.judgment_events = []
            return result
        finally:
            self.busy = False
            self.current_task = None
            self._interrupt = False

    def _record_frame(self, frame) -> Optional[str]:
        self._frame_count += 1
        frame_hash = sha256_hex(
            self._frame_hash + str(frame.idx) + frame.utterance_id + frame.scene)
        self._frame_hash = frame_hash
        if self._frame_count % 30 == 0:
            self.audit.append("frame_checkpoint", self.room_id, {
                "hash": frame_hash, "frame_idx": frame.idx,
                "utterance_id": frame.utterance_id, "scene": frame.scene})
            return frame_hash
        return None
