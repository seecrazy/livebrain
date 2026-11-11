"""直播场景包（V4.4）：直播不一定是卖货——聊天/唱歌/相声/脱口秀皆可。

用法：LiveBrain(format_id="standup")，或控制台
python3 -m livebrain.console --format music
场景无关的决策骨架不变，生意域由场景包提供（见 base.RoomFormat）。
"""
from .base import RoomFormat, available, build_task, create, register
from .packs import (ChatFormat, CrosstalkFormat, EcommerceFormat,
                    MusicFormat, StandupFormat)

__all__ = [
    "RoomFormat", "register", "create", "available", "build_task",
    "EcommerceFormat", "ChatFormat", "MusicFormat", "StandupFormat",
    "CrosstalkFormat",
]
