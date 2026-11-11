"""推流输出（M3 前的低配验证通道）。

lowfi.LowFiStreamer：ffmpeg（lavfi 画面 + drawtext 字幕 + mp3 音频管道）
→ RTMP/本地 FLV。无需 GPU 与平台开放者资质，先验证真实推流链路。
"""
