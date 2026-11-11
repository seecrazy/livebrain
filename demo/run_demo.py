"""模拟直播间演示：一条龙跑通 V4.1 的全部关键机制。

剧本与回放工具（tools/replay.py）共用 livebrain/scenarios.py，所见即所测。
运行：python3 demo/run_demo.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livebrain.config import Settings
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform
from livebrain.scenarios import SCRIPT, build_demo_script


def banner(title: str) -> None:
    print("\n" + "=" * 62)
    print(title)
    print("=" * 62)


def main() -> None:
    audit_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "audit_demo.jsonl")
    if os.path.exists(audit_path):
        os.remove(audit_path)

    platform = MockPlatform("room-demo")

    def on_speech(utterance_id: str, sentence: str) -> None:
        print("  [主播] %s" % sentence)

    settings = Settings(clock_scale=0.0, aggregate_window_s=0.4,
                        fast_reply_per_min=30, llm_reply_per_min=30,
                        breaker_threshold=3)
    brain = LiveBrain(platform=platform, settings=settings,
                      speech_sink=on_speech, llm_script=SCRIPT,
                      audit_path=audit_path, room_id="room-demo")

    print("剧本：暖场互动 -> 快轨价格 -> 中轨RAG -> 注入攻击x2 -> 敏感/诱导拦截")
    print("      -> 幻觉数字 -> 无支持宣称 -> 自由承诺 -> LLM降级链 -> 逼单上链接")
    print("      -> 平台判罚升级 -> 恢复 -> 人工接管/交回/发券 -> 人设切换 -> 打断\n")

    for delay, event in build_demo_script(room_id="room-demo"):
        brain.schedule(delay, event)

    print("---- 直播时间线 ----")
    asyncio.run(brain.run_until_idle())

    audit = brain.audit
    spoken = brain.spoken_texts()
    all_text = "".join(spoken)

    banner("运行结果")
    print("话术总数：%d 条（打断 %d 条）" % (
        len(brain.speech_results),
        sum(1 for r in brain.speech_results if r.interrupted)))
    print("快轨价格逐字匹配：", "¥119" in all_text and "满100减10" in all_text)
    print("幻觉数字拦截（199 未出稿）：", "199" not in all_text)
    print("注入弹幕隔离：", audit.count("quarantine"), "条（0 条进入 LLM）")
    print("承诺队列核销：", [(p.ops.action, p.status) for p in brain.promises.promises])
    print("平台运营动作：", platform.ops_log)
    print("降级链：当前 provider =", brain.llm_chain.current_name(),
          "| 切换审计 =", audit.count("provider_switch"), "次")
    print("判罚事件：", len(brain.judgments), "次 -> 升级保守模板",
          sum(1 for r in brain.speech_results
              if r.task.source == "template_escalated"), "条")
    print("人工接管/交回：", audit.count("takeover"), "/", audit.count("rehandoff"))
    print("审计条目：%d 条 | 哈希链校验：%s" % (
        len(audit.entries), audit.verify()[0]))
    print("审计日志已写入：%s" % audit_path)
    if brain.alerts:
        print("运营告警：", brain.alerts)


if __name__ == "__main__":
    main()
