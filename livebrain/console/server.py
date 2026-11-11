"""运营控制台 HTTP 服务（零第三方依赖，stdlib 实现）。

- GET  /            控制台单页
- GET  /api/state   编排器状态快照（JSON，前端 800ms 轮询）
- POST /api/control 运营指令 {action, params}，转发进编排器事件总线
                    takeover / rehandoff / resume / persona_switch /
                    switch_product / human_ops
安全：仅绑定 127.0.0.1（本地值守台），不对外网暴露。
"""
import asyncio
import json
import os
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Deque, Dict, Optional, Tuple

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_CONTROL_ACTIONS = {
    "takeover", "rehandoff", "resume", "persona_switch",
    "switch_product", "human_ops", "demo_schedule", "record_toggle",
}


class ConsoleHub:
    """HTTP 线程与编排器事件循环之间的桥：快照走 run_coroutine_threadsafe，
    控制指令进线程安全队列，由运行时循环转发进事件总线。"""

    def __init__(self, brain, loop, extra_state=None) -> None:
        self.brain = brain
        self.loop = loop
        self.extra_state = extra_state          # 运行时附加状态（录制/推流等）
        self.commands: Deque[Tuple[str, Dict]] = deque()
        self.command_log: Deque[Dict] = deque(maxlen=50)

    def snapshot(self) -> Dict:
        async def _call():
            state = self.brain.state_snapshot()
            if self.extra_state:
                state.update(self.extra_state())
            return state

        future = asyncio.run_coroutine_threadsafe(_call(), self.loop)
        return future.result(timeout=3)

    def submit(self, action: str, params: Dict) -> Tuple[bool, str]:
        if action not in _CONTROL_ACTIONS:
            return False, "unknown_action:%s" % action
        self.commands.append((action, dict(params)))
        self.command_log.append({"action": action, "params": dict(params)})
        return True, "queued"


class _Handler(BaseHTTPRequestHandler):
    hub: ConsoleHub = None          # 由 serve() 注入类属性
    token: str = None               # API 鉴权 token（None=不鉴权，仅测试/内嵌）

    def log_message(self, fmt, *args):   # 静默访问日志
        pass

    def _authorized(self) -> bool:
        if not self.token:
            return True
        header = self.headers.get("X-LiveBrain-Token", "")
        query = ""
        if "?" in self.path:
            query = self.path.split("?", 1)[1]
        from urllib.parse import parse_qs
        token_param = parse_qs(query).get("token", [""])[0]
        return header == self.token or token_param == self.token

    def _send_json(self, payload: Dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str, content_type: str) -> None:
        path = os.path.join(STATIC_DIR, filename)
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            self._send_json({"error": "not_found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                   # noqa: N802（stdlib 约定）
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/") and not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        if path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
        elif path == "/app.js":
            self._send_static("app.js", "application/javascript; charset=utf-8")
        elif path == "/style.css":
            self._send_static("style.css", "text/css; charset=utf-8")
        elif path.startswith("/api/state"):
            try:
                self._send_json(self.hub.snapshot())
            except Exception as exc:
                self._send_json({"error": str(exc)}, 500)
        else:
            self._send_json({"error": "not_found"}, 404)

    def do_POST(self):                  # noqa: N802
        if self.path.split("?", 1)[0] != "/api/control":
            self._send_json({"error": "not_found"}, 404)
            return
        if not self._authorized():
            self._send_json({"error": "unauthorized"}, 401)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json({"error": "bad_request"}, 400)
            return
        ok, detail = self.hub.submit(payload.get("action", ""),
                                     payload.get("params", {}))
        self._send_json({"ok": ok, "detail": detail},
                        200 if ok else 400)


def serve(hub: ConsoleHub, host: str = "127.0.0.1",
          port: int = 8765, daemon: bool = True, token: str = None):
    """启动 HTTP 服务（阻塞前先绑定端口以便测试取实际端口）。

    token 非空时 /api/* 需带 X-LiveBrain-Token 头或 ?token= 查询参数。
    """
    handler = type("BoundHandler", (_Handler,), {"hub": hub, "token": token})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = daemon
    return server
