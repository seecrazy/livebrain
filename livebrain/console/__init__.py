"""运营控制台（V4.3 增补）：网页版值守大屏 + API。

- server.py：零依赖 HTTP 服务（状态快照 / 控制指令 / 静态页）
- __main__.py：实时模拟运行时（弹幕流驱动 + HTTP 服务）
- static/：前端单页（原生 HTML/CSS/JS，无构建链）

Mac 原生壳见 mac/（WKWebView + 全局热键）。
"""
