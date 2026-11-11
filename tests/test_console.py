"""运营控制台（V4.3）：状态快照 + HTTP API + 控制指令闭环。"""
import asyncio
import json
import threading
import time
import urllib.request

from livebrain.console.__main__ import ConsoleRuntime
from livebrain.console.server import serve
from livebrain.config import Settings
from livebrain.events import danmu_event, metric_event
from livebrain.orchestrator import LiveBrain
from livebrain.platform.mock_platform import MockPlatform
from tests.helpers import FakeClock  # noqa: F401


# ---------------------------------------------------------------- 快照单元
def test_state_snapshot_after_script():
    from livebrain.scenarios import SCRIPT, build_demo_script, replay_settings_dict

    platform = MockPlatform("room-snap")
    brain = LiveBrain(platform=platform,
                      settings=Settings.from_dict(replay_settings_dict()),
                      llm_script=SCRIPT, room_id="room-snap")
    for delay, event in build_demo_script(room_id="room-snap"):
        brain.schedule(delay, event)

    async def run():
        await brain.run_until_idle()
        return brain.state_snapshot()

    state = asyncio.run(run())
    assert state["room"] == "room-snap" and state["started"]
    assert state["mode"] == "ai"
    assert state["stage"] in ("warmup", "explain", "closing", "valley")
    assert state["audit"]["verified"] and state["audit"]["count"] > 10
    assert state["stats"]["utterances"] > 5
    assert len(state["danmu_feed"]) > 5
    assert any(d["quarantined"] for d in state["danmu_feed"]), "注入隔离应在弹幕流可见"
    assert any(d["intent"] == "price_stock" for d in state["danmu_feed"])
    assert state["compliance"]["armed"]
    assert state["persona"] == "ajing"          # E2E 剧本末尾切换过人设


def test_state_snapshot_visual_source_in_human_mode():
    from livebrain.mixed.capture import MockHumanCapture

    platform = MockPlatform("room-vis", human_capture=MockHumanCapture())
    brain = LiveBrain(platform=platform, settings=Settings(clock_scale=0.0),
                      room_id="room-vis")

    async def run():
        await brain.start()
        await brain._enter_human("manual")
        await brain.pipeline.human_tick()
        return brain.state_snapshot()

    state = asyncio.run(run())
    assert state["mode"] == "human"
    assert state["visual_source"] == "human"
    assert state["visual_history"] == ["human"]


# ---------------------------------------------------------------- HTTP 集成
def _http(method: str, url: str, body=None):
    request = urllib.request.Request(url, method=method)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, data=data, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


class _Harness:
    """后台线程跑 ConsoleRuntime（真实 asyncio 循环），HTTP 服务随机端口。"""

    def __init__(self):
        self.runtime = ConsoleRuntime(room_id="room-http", port=0)
        self.server = serve(self.runtime.hub, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._run_brain, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def _run_brain(self):
        asyncio.set_event_loop(self.runtime.loop)
        try:
            self.runtime.loop.run_until_complete(self.runtime.run())
        except Exception:
            pass

    def stop(self):
        self.runtime.stop()
        self.server.shutdown()


def test_console_http_end_to_end():
    harness = _Harness()
    try:
        # 静态页
        with urllib.request.urlopen(harness.base + "/", timeout=5) as res:
            html = res.read().decode("utf-8")
        assert "播控大脑" in html and "运营控制台" in html

        # 状态快照
        for _ in range(20):        # 等运行时就绪
            try:
                status, state = _http("GET", harness.base + "/api/state")
                break
            except Exception:
                time.sleep(0.2)
        assert status == 200 and state["room"] == "room-http"
        assert state["mode"] == "ai" and state["compliance"]["armed"]

        # 控制闭环：接管 -> 状态变为真人模式 -> 交回
        status, resp = _http("POST", harness.base + "/api/control",
                             {"action": "takeover",
                              "params": {"reason": "console_test"}})
        assert status == 200 and resp["ok"]
        deadline = time.time() + 5
        while time.time() < deadline:
            _, state = _http("GET", harness.base + "/api/state")
            if state["mode"] == "human" and state["visual_source"] == "human":
                break
            time.sleep(0.15)
        assert state["mode"] == "human", "接管指令必须生效"

        status, _ = _http("POST", harness.base + "/api/control",
                          {"action": "rehandoff", "params": {}})
        deadline = time.time() + 5
        while time.time() < deadline:
            _, state = _http("GET", harness.base + "/api/state")
            if state["mode"] == "ai":
                break
            time.sleep(0.15)
        assert state["mode"] == "ai", "交回指令必须生效"

        # 未知动作拒绝
        try:
            _http("POST", harness.base + "/api/control",
                  {"action": "nuke_everything", "params": {}})
            raise AssertionError("未知动作应被拒绝")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400

        # 弹幕流随运行时持续增长
        time.sleep(1.2)
        _, state = _http("GET", harness.base + "/api/state")
        assert len(state["danmu_feed"]) >= 2
    finally:
        harness.stop()
