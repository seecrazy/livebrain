"""全局配置：降级链、延迟预算、回复率预算、阈值、熔断参数。"""
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class Settings:
    # 延迟预算（毫秒）
    fast_budget_ms: int = 500          # 快轨端到端目标
    mid_budget_ms: int = 4000          # 中轨超时阈值，超时落保守模板
    filler_after_ms: int = 1500        # 等待超过该时长先播 filler

    # filler 调度：中轨生成期间若管线空闲，先播衔接话术（默认关，
    # 真实 LLM 延迟下开启；Mock 零延迟场景无意义）
    emit_filler: bool = False

    # 混播排班（V4.2）：开播后按时段切换 AI/真人，如
    # [{"duration_s": 600, "mode": "ai", "label": "长尾品"},
    #  {"duration_s": 1800, "mode": "human", "label": "主推真人场"}]
    mixed_schedule: List[dict] = field(default_factory=list)

    # 场景包主动推进（V4.4）：连续空闲 N 个 tick 且无事可做时，
    # 场景包提供主动节目内容（排品/话题/段子/报幕/对词）。0=关闭。
    proactive_after_ticks: int = 0

    # 弹幕处理
    danmu_max_len: int = 120
    aggregate_window_s: float = 15.0
    fast_reply_per_min: int = 15       # 快轨回复率预算
    llm_reply_per_min: int = 6         # LLM 轨回复率预算

    # 数据新鲜度与库存
    stale_after_s: float = 30.0
    low_stock_ratio: float = 0.2

    # 熔断器
    breaker_threshold: int = 3         # 窗口内失败次数阈值
    breaker_window_s: float = 60.0
    breaker_cooldown_s: float = 120.0

    # 场控
    warmup_online: int = 50
    valley_drop_ratio: float = 0.30    # 在线较 5 分钟峰值下降比例
    hysteresis_ticks: int = 2          # 状态切换需连续 N 个周期满足条件

    # 人设
    manual_persona_switch_limit: int = 3

    # 时钟缩放（demo/测试）
    clock_scale: float = 1.0

    # 能力降级链：名称 -> provider 名列表（M1 全部 Mock，M2 换真实实现）
    chains: Dict[str, List[str]] = field(
        default_factory=lambda: {
            "llm": ["mock_llm_primary", "mock_llm_backup"],
            "tts": ["mock_tts"],
            "renderer": ["mock_renderer"],
        }
    )

    def chain(self, name: str) -> List[str]:
        return list(self.chains.get(name, []))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Settings":
        base = cls()
        for key, value in data.items():
            if hasattr(base, key):
                setattr(base, key, value)
        return base
