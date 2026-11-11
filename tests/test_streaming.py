"""低配真推流（P1-8）：命令构建/字幕/静音兜底/本地 FLV 冒烟（需 ffmpeg）。"""
import os
import shutil
import tempfile
import time

import pytest

from livebrain.streaming.lowfi import LowFiStreamer


def test_command_build_and_subtitles_dry_run():
    streamer = LowFiStreamer("rtmp://example.com/live/key", dry_run=True)
    cmd = streamer.build_command()
    assert "flv" in cmd and "rtmp://example.com/live/key" in cmd
    assert "pipe:0" in cmd, "音频走 stdin 管道"
    assert streamer.font, "应找到可用字体（drawtext 字幕）"
    assert any("textfile" in part for part in cmd), "字幕用 textfile+reload"

    streamer.say("第一句话", b"\xff\xfb00")
    streamer.say("第二句话")                       # 无音频 -> 静音兜底
    with open(streamer.subtitle_path, encoding="utf-8") as fh:
        assert fh.read() == "第二句话"
    assert streamer.sent_count == 2


def test_missing_ffmpeg_clear_error():
    try:
        LowFiStreamer("rtmp://x/y", ffmpeg_bin="no-such-ffmpeg")
    except RuntimeError as exc:
        assert "ffmpeg" in str(exc)
    else:
        raise AssertionError("缺 ffmpeg 必须报清晰错误")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
def test_local_flv_smoke():
    """限时 FLV 落盘冒烟：真实编码/字幕/音频管道端到端。

    复刻已验证的最小路径：-t 限时 + stdin 喂静音后立即 EOF，
    ffmpeg 自然收尾落盘。直播推流（duration_s=None）为无限流，
    RTMP 场景无收尾包问题。
    """
    out = os.path.join(tempfile.mkdtemp(), "lb-smoke.flv")
    streamer = LowFiStreamer(out, duration_s=3)
    try:
        streamer._audio.write(streamer._silence() * 4)   # 追加静音音轨
        streamer._audio.close()                          # EOF：自然收尾
        streamer.proc.wait(timeout=15)
        assert streamer.proc.returncode == 0
    finally:
        streamer.stop()
    assert os.path.exists(out) and os.path.getsize(out) > 3 * 1024, \
        "FLV 应有实质内容（视频帧+音频）"
