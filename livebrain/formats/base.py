"""直播场景包（V4.4 增补）：直播不一定是卖货。

决策骨架（三轨/消毒/打断/审计/混播/接管）场景无关；生意域做成可插拔的
RoomFormat 场景包，提供：场控策略表、空闲主动推进（节目内容）、
场景意图（点歌/段子）、礼物感谢、播报完成回调。

内置五包：ecommerce 电商带货 / chat 聊天陪伴 / music 唱歌演艺 /
standup 单口相声·脱口秀 / crosstalk 多人相声（对词轮转）。
"""
from typing import Dict, Optional

from ..decision.field_controller import StageStrategy
from ..decision.types import PRIORITY_TEMPLATE, SpeechTask
from ..util import uid

_GIFT_THANKS_DEFAULT = "感谢{name}送的{gift}，爱你么么哒～"


def build_task(sentences, source: str, origin: str = "",
               priority: int = PRIORITY_TEMPLATE, emotion: str = "cheerful",
               track: str = "template", clock=None) -> SpeechTask:
    return SpeechTask(
        task_id=uid("spk"), track=track, sentences=list(sentences),
        priority=priority, emotion=emotion, ops=[], origin=origin,
        source=source, facts={}, created_ts=clock.now() if clock else 0.0)


class RoomFormat:
    """场景包基类。所有方法返回 None 表示"不处理，走默认"。"""

    format_id = "ecommerce"
    display_name = "电商带货"
    stage_display = {
        "warmup": "暖场期", "explain": "讲解期", "closing": "逼单期",
        "valley": "低谷期",
    }

    def stage_strategies(self) -> Dict[str, StageStrategy]:
        """覆盖默认场控策略（同四阶段键，参数与情绪按场景定）。"""
        return {}

    async def proactive(self, brain) -> Optional[SpeechTask]:
        """空闲时的主动节目推进（没人提问也要持续播）。

        内容优先级：用户内容（--data）> AI 原创（settings.creative_llm）> 内置种子。
        """
        return None

    def handle_song_request(self, brain, text: str,
                            user_id: str) -> Optional[SpeechTask]:
        """点歌意图；默认非唱歌场景礼貌婉拒。"""
        return build_task(
            ["咱们今天是" + self.display_name + "专场，不唱歌哈，宝宝点个别的～"],
            source="format:decline_song", origin=text, clock=brain.clock)

    def handle_joke_request(self, brain, text: str,
                            user_id: str) -> Optional[SpeechTask]:
        """段子意图；默认婉拒。"""
        return build_task(
            ["今天不搞笑专业哈，宝宝想听段子改天开个专场～"],
            source="format:decline_joke", origin=text, clock=brain.clock)

    def interact_reply(self, brain) -> Optional[str]:
        """场景化互动回复模板；None=用编排器默认。"""
        return None

    def gift_thanks(self, brain, user_id: str, gift: str,
                    count: int) -> SpeechTask:
        text = _GIFT_THANKS_DEFAULT.format(
            name=user_id, gift=gift if count <= 1 else "%s×%d" % (gift, count))
        return build_task([text], source="format:gift_thanks",
                          origin="gift:%s" % gift, clock=brain.clock)

    def on_speech_done(self, brain, result) -> None:
        """播报完成回调（含打断标记）：段子未讲完回队等场景用。"""
        return None


_REGISTRY = {}


def register(format_cls) -> None:
    _REGISTRY[format_cls.format_id] = format_cls


def create(format_id: str) -> RoomFormat:
    if format_id not in _REGISTRY:
        raise ValueError("未知直播场景：%s（可选 %s）"
                         % (format_id, "/".join(sorted(_REGISTRY))))
    return _REGISTRY[format_id]()


def available() -> list:
    return sorted(_REGISTRY)
