"""低配真推流（P1-8）：ffmpeg 合成画面+字幕+TTS 音频 → RTMP / 本地 FLV。

目的：在接 GPU 渲染与真平台（M3）之前，用最低成本验证真实推流链路
（编码、推流、字幕、音频、断流）。无需 GPU，无需平台开放者资质——
推到 B 站/视频号"测试直播间"即可。

画面：lavfi 纯色底 + drawtext 字幕（textfile+reload=1，每句实时换字幕）。
音频：mp3 流经 stdin（pipe:0）喂入（mp3 帧可拼接）；TTS 失败写静音帧；
启动先喂静音预热探测，停止时关 stdin 让 ffmpeg 优雅收尾（写清 trailer）。
合规：AI 标识常驻画面顶部（drawtext 固定层，叠加字幕之上）。
"""
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",            # macOS（旧版）
    "/System/Library/Fonts/Supplemental/Songti.ttc", # macOS（无空格中文字体）
    "/System/Library/Fonts/Supplemental/Kailasa.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux CI
]
AI_LABEL = "AI虚拟主播"


class LowFiStreamer:
    def __init__(self, target: str, ffmpeg_bin: str = "ffmpeg",
                 size: str = "1280x720", fps: int = 25,
                 font_path: Optional[str] = None,
                 subtitle_path: Optional[str] = None,
                 duration_s: Optional[float] = None,
                 dry_run: bool = False) -> None:
        if shutil.which(ffmpeg_bin) is None and not dry_run:
            raise RuntimeError("未找到 ffmpeg（brew install ffmpeg / apt install ffmpeg）")
        self.target = target
        self.size = size
        self.fps = fps
        self.duration_s = duration_s          # 限时输出（测试/预录用；直播为 None）
        # drawtext 的 fontfile 裸拼进 filter 串：跳过含空格等特殊字符的路径
        self.font = next(
            (f for f in [font_path] + FONT_CANDIDATES
             if f and os.path.exists(f)
             and not any(c in f for c in " ':\"")), None)
        self.subtitle_path = subtitle_path or os.path.join(
            tempfile.mkdtemp(prefix="livebrain-stream-"), "subtitle.txt")
        os.makedirs(os.path.dirname(self.subtitle_path), exist_ok=True)
        with open(self.subtitle_path, "w", encoding="utf-8") as fh:
            fh.write("直播马上开始…")
        self.proc: Optional[subprocess.Popen] = None
        self._audio = None
        self.sent_count = 0
        self.dry_run = dry_run
        self.buffered_mp3 = 0
        # 字幕/AI 标识依赖 drawtext 滤镜；缺失则降级为纯画面+音频
        # （合规注意：无 AI 标识的画面仅可用于链路验证测试间，不可商用开播）
        self.text_overlay = dry_run or self._probe_drawtext(ffmpeg_bin)
        if not self.text_overlay:
            print("警告：ffmpeg 缺 drawtext 滤镜，字幕与 AI 标识不可用"
                  "（仅限链路验证，不可商用开播）")
        if not dry_run:
            self._start()

    @staticmethod
    def _probe_drawtext(ffmpeg_bin: str) -> bool:
        try:
            out = subprocess.run([ffmpeg_bin, "-hide_banner", "-filters"],
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL,
                                 timeout=5).stdout
            return b" drawtext" in out or b"drawtext " in out or \
                b"drawtext\t" in out or b"drawtext" in out.split(b"T..")[-1][:0] or \
                b"drawtext" in out
        except Exception:
            return False

    # ------------------------------------------------------------------
    def _drawtext_filters(self) -> List[str]:
        filters = []
        if self.font and self.text_overlay:
            filters.append(
                "drawtext=fontfile=%s:text='%s':fontcolor=white@0.9:"
                "fontsize=22:x=(w-text_w)/2:y=28"
                % (self.font, AI_LABEL))
            filters.append(
                "drawtext=fontfile=%s:textfile=%s:reload=1:fontcolor=white:"
                "fontsize=34:x=(w-text_w)/2:y=h-140:box=1:boxcolor=black@0.55:"
                "boxborderw=14" % (self.font, self.subtitle_path))
        return filters

    def build_command(self) -> List[str]:
        vf = ",".join(self._drawtext_filters())
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-re",
            "-f", "lavfi", "-i",
            "color=c=0x141B2B:s=%s:r=%d" % (self.size, self.fps),
            "-f", "mp3", "-i", "pipe:0",
            *(["-vf", vf] if vf else []),
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-b:v", "1200k",
            "-c:a", "aac", "-ar", "24000", "-b:a", "128k",
            *(["-t", str(self.duration_s)] if self.duration_s else []),
            "-f", "flv", self.target,
        ]

    def _start(self) -> None:
        self.proc = subprocess.Popen(
            self.build_command(), stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._audio = self.proc.stdin                     # mp3 流走 stdin
        # 预热：先喂一段静音，让 mp3 探测立即拿到连续帧
        silence = self._silence()
        if silence:
            try:
                self._audio.write(silence * 3)
            except (BrokenPipeError, OSError):
                pass

    # ------------------------------------------------------------------
    def say(self, sentence: str, mp3: bytes = b"") -> None:
        """一句话上屏（字幕）+ 入音轨（mp3 流；缺省写静音帧防音频断流）。"""
        self.sent_count += 1
        with open(self.subtitle_path, "w", encoding="utf-8") as fh:
            fh.write(sentence[:60])
        payload = mp3 or self._silence()
        if self.dry_run:
            self.buffered_mp3 += len(payload)
            return
        if self._audio is not None and payload:
            try:
                self._audio.write(payload)
            except (BrokenPipeError, OSError):
                pass                                  # 推流端断开：字幕照走

    def _silence(self) -> bytes:
        if not hasattr(self, "_silence_cache"):
            self._silence_cache = b""
            try:                                       # 0.2s 静音 mp3（ffmpeg 现造）
                out = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
                     "-t", "0.2", "-c:a", "libmp3lame", "-b:a", "32k",
                     "-f", "mp3", "pipe:1"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    timeout=5).stdout
                self._silence_cache = out
            except Exception:
                self._silence_cache = b""
        return self._silence_cache

    def stop(self) -> None:
        if self._audio is not None:
            try:
                self._audio.close()          # EOF -> ffmpeg 优雅收尾写 trailer
            except OSError:
                pass
        if self.proc is not None:
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except Exception:
                    self.proc.kill()
            self.proc = None

    def healthy(self) -> bool:
        return self.proc is None or self.proc.poll() is None
