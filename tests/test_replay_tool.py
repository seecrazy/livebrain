"""回放测试工具（tools/replay.py）：录制/回放/不变量校验。"""
import asyncio
import importlib.util
import json
import os
import tempfile

_TOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tools", "replay.py")
_spec = importlib.util.spec_from_file_location("replay_tool", _TOOLS)
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)


def test_record_and_check_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "session.jsonl")
        assert replay.cmd_record(type("A", (), {"out": path})()) == 0
        with open(path, encoding="utf-8") as fh:
            lines = [json.loads(x) for x in fh if x.strip()]
        assert len(lines) >= 30 and all("delay" in x and "event" in x for x in lines)
        code = replay.cmd_check(type("A", (), {"in_path": path})())
    assert code == 0, "标准剧本回放必须全部通过不变量"


def test_check_invariants_detects_pending_promise():
    from livebrain.config import Settings
    from livebrain.orchestrator import LiveBrain
    from livebrain.platform.mock_platform import MockPlatform
    from livebrain.scenarios import SCRIPT, build_demo_script, replay_settings_dict

    platform = MockPlatform("room-rp")
    brain = LiveBrain(platform=platform,
                      settings=Settings.from_dict(replay_settings_dict()),
                      llm_script=SCRIPT, room_id="room-rp")
    for delay, event in build_demo_script(room_id="room-rp"):
        brain.schedule(delay, event)
    asyncio.run(brain.run_until_idle())

    passed, _problems = replay.check_invariants(brain)
    assert passed

    # 人为制造未核销承诺 -> I4 必须报警
    brain.promises.promises[0].status = "pending"
    passed, problems = replay.check_invariants(brain)
    assert not passed
    assert any(p.startswith("I4") for p in problems)


def test_check_invariants_detects_dirty_speech():
    """I3：出稿含违禁词时必须报警。"""
    from livebrain.config import Settings
    from livebrain.orchestrator import LiveBrain
    from livebrain.platform.mock_platform import MockPlatform
    from livebrain.scenarios import replay_settings_dict

    brain = LiveBrain(platform=MockPlatform("room-dirty"),
                      settings=Settings.from_dict(replay_settings_dict()),
                      room_id="room-dirty")

    class _R:  # 鸭子类型注入一条脏话术
        spoken_text = "这款全网最低，加微信私聊"

    class _B:
        pass

    fake = _B()
    fake.audit = brain.audit
    fake.speech_results = [_R()]
    fake.store = brain.store
    fake.promises = brain.promises
    fake.llm_seen_user_inputs = brain.llm_seen_user_inputs
    passed, problems = replay.check_invariants(fake)
    assert not passed
    assert any(p.startswith("I3") for p in problems)
