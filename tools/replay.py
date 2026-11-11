#!/usr/bin/env python3
"""弹幕回放测试工具（DESIGN §9 红队回归 / M2）。

用法：
  录制标准剧本到 JSONL：
    python3 tools/replay.py record --out replay_session.jsonl
  回放并校验不变量（CI 可用，违反则退出码 1）：
    python3 tools/replay.py check --in replay_session.jsonl

不变量（每条都是商用红线）：
  I1 审计哈希链完好（可证明未篡改）
  I2 被隔离的注入弹幕从未出现在任何 LLM 输入中
  I3 所有出稿话术：占位符全部填充、三道过滤通过
  I4 承诺队列无未核销项
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livebrain.config import Settings
from livebrain.decision import filters, slots
from livebrain.events import LiveEvent
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform
from livebrain.scenarios import SCRIPT, build_demo_script, replay_settings_dict


def _run_brain(events, room_id: str) -> LiveBrain:
    platform = MockPlatform(room_id)
    brain = LiveBrain(platform=platform,
                      settings=Settings.from_dict(replay_settings_dict()),
                      llm_script=SCRIPT, room_id=room_id)
    for delay, event in events:
        brain.schedule(delay, event)
    asyncio.run(brain.run_until_idle())
    return brain


def check_invariants(brain: LiveBrain):
    """返回 (是否通过, 问题列表)。brain 为鸭子类型，测试可注入畸形对象。"""
    problems = []

    ok, bad_seq = brain.audit.verify()                                # I1
    if not ok:
        problems.append("I1 审计哈希链在 seq=%s 处断裂" % bad_seq)

    quarantined = [e.payload.get("text", "")                            # I2
                   for e in brain.audit.by_type("quarantine")]
    seen = "\n".join(brain.llm_seen_user_inputs())
    for text in quarantined:
        probe = (text or "")[:10]
        if probe and probe in seen:
            problems.append("I2 注入弹幕进入 LLM 输入: %s" % probe)

    product = brain.store.get("SKU001")                                 # I3
    category = product.category if product else ""
    qual_flags = product.qual_flags if product else []
    for result in brain.speech_results:
        text = result.spoken_text
        if slots.extract_slots(text):
            problems.append("I3 出稿含未填充占位符: %s" % text[:40])
        verdict = filters.check(text, category, qual_flags)
        if not verdict.passed:
            problems.append("I3 出稿被过滤拦截(应零拦截): %s %s"
                            % (verdict.blocked, text[:40]))

    if brain.promises.has_pending():                                    # I4
        problems.append("I4 存在未核销承诺: %d 条"
                        % len(brain.promises.pending()))
    return (not problems), problems


def _serialize(event: LiveEvent) -> dict:
    return event.to_dict()


def cmd_record(args) -> int:
    events = build_demo_script(room_id="room-record")
    with open(args.out, "w", encoding="utf-8") as fh:
        for delay, event in events:
            fh.write(json.dumps(
                {"delay": round(delay, 3), "event": _serialize(event)},
                ensure_ascii=False) + "\n")
    print("已录制 %d 条事件 -> %s" % (len(events), args.out))
    return 0


def cmd_check(args) -> int:
    events = []
    with open(args.in_path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            record = json.loads(line)
            events.append((record["delay"], LiveEvent(**record["event"])))
    brain = _run_brain(events, room_id="room-replay")
    passed, problems = check_invariants(brain)
    utterances = brain.speech_results
    print("回放 %d 条事件 -> %d 条话术 | 审计 %d 条"
          % (len(events), len(utterances), len(brain.audit.entries)))
    if passed:
        print("不变量校验：全部通过（I1 哈希链 / I2 注入隔离 / I3 出稿干净 / I4 承诺核销）")
        return 0
    print("不变量校验失败：")
    for problem in problems:
        print("  - %s" % problem)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="LiveBrain 弹幕回放测试工具")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record", help="录制标准剧本")
    rec.add_argument("--out", required=True)
    rec.set_defaults(func=cmd_record)
    chk = sub.add_parser("check", help="回放并校验不变量")
    chk.add_argument("--in", dest="in_path", required=True)
    chk.set_defaults(func=cmd_check)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
