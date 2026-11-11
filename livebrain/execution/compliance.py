"""AI 标识门禁（DESIGN §7.3）：推流前 Hook 的架构级等价物。

标识规格来自平台 compliance profile（文案/位置/最小占比）；
未武装（armed）时流式管线拒绝产出任何可推流帧——不可绕过，不是配置项。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ComplianceProfile:
    platform: str
    label_text: str                  # 如 "AI虚拟主播"
    min_area_ratio: float            # 标识最小画面占比
    position: str = "top-center"     # 部分平台要求醒目位置，角落小字不合规
    requires_registration: bool = True
    audio_hint_interval_s: int = 300  # 音频周期提示间隔


class ComplianceNotArmed(Exception):
    pass


class ComplianceOverlay:
    def __init__(self) -> None:
        self.profile: Optional[ComplianceProfile] = None
        self.armed: bool = False

    def arm(self, profile: ComplianceProfile) -> None:
        if not profile.label_text:
            raise ValueError("compliance profile missing label_text")
        if profile.min_area_ratio < 0.05:
            raise ValueError("标识占比低于平台最低要求")
        self.profile = profile
        self.armed = True

    def disarm(self) -> None:
        self.armed = False
