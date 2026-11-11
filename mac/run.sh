#!/bin/bash
# 启动本地控制台服务（如未运行）并打开 Mac 原生应用
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PORT="${LIVEBRAIN_PORT:-8765}"

if ! curl -sf "http://127.0.0.1:$PORT/api/state" >/dev/null 2>&1; then
    echo "启动播控大脑控制台服务（端口 $PORT）…"
    (cd "$ROOT" && nohup python3 -m livebrain.console --port "$PORT" \
        >/tmp/livebrain-console.log 2>&1 &)
    for _ in $(seq 1 60); do
        curl -sf "http://127.0.0.1:$PORT/api/state" >/dev/null 2>&1 && break
        sleep 0.25
    done
fi

if [ ! -d "$HERE/LiveBrain Console.app" ]; then
    echo "首次运行，构建应用…"
    "$HERE/build.sh"
fi
open "$HERE/LiveBrain Console.app"
