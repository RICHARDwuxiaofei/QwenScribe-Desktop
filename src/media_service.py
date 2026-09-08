"""FFprobe/FFmpeg media inspection, extraction, silence detection and cutting."""

from __future__ import annotations

import json
import logging
import math
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .exceptions import (
    FFmpegNotFoundError,
    MediaProcessingError,
    NoAudioStreamError,
    UserCancelledError,
)


LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[float], None]

_SILENCE_START = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float
    audio_stream_count: int


def _windows_process_flags() -> tuple[int, subprocess.STARTUPINFO | None]:
    if not hasattr(subprocess, "CREATE_NO_WINDOW"):
        return 0, None
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    return subprocess.CREATE_NO_WINDOW, startup


class MediaService:
    """Owns the currently running external process so cancellation is immediate."""

    def __init__(self, application_directory: Path) -> None:
        self.application_directory = Path(application_directory)
        self.ffmpeg = self._find_executable("ffmpeg.exe", "ffmpeg")
        self.ffprobe = self._find_executable("ffprobe.exe", "ffprobe")
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()
        self._creationflags, self._startupinfo = _windows_process_flags()

    def _find_executable(self, bundled_name: str, path_name: str) -> Path:
        bundled = self.application_directory / "bin" / bundled_name
        if bundled.is_file():
            return bundled
        found = shutil.which(path_name)
        if found:
            return Path(found)
        raise FFmpegNotFoundError(
            f"找不到 {path_name}。请将 {bundled_name} 放入程序的 bin 目录，"
            "或安装 FFmpeg 并加入系统 PATH。"
        )

    def cancel_current_process(self) -> None:
        """Terminate the active FFmpeg process from any thread."""
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            LOGGER.info("正在终止 FFmpeg 子进程 PID=%s", process.pid)
            process.terminate()

    def probe(self, input_path: Path, cancel_event: threading.Event) -> MediaInfo:
        if not input_path.is_file():
            raise MediaProcessingError(f"输入文件不存在：{input_path}")
        command = [
            str(self.ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=index,codec_type,duration",
            "-of",
            "json",
            str(input_path),
        ]
        output = self._run_capture(command, cancel_event, "FFprobe 检查失败")
        try:
            payload = json.loads(output)
            streams = payload.get("streams", [])
            audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
            if not audio_streams:
                raise NoAudioStreamError("该文件不包含音频轨道")
            duration_value = payload.get("format", {}).get("duration")
            if duration_value is None:
                duration_value = audio_streams[0].get("duration")
            duration = float(duration_value)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError("non-positive duration")
        except NoAudioStreamError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise MediaProcessingError("无法从 FFprobe 结果读取有效媒体时长") from error
        return MediaInfo(duration=duration, audio_stream_count=len(audio_streams))

    def extract_audio(
        self,
        input_path: Path,
        output_path: Path,
        duration: float,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
    ) -> None:
        command = [
            str(self.ffmpeg),
            "-y",
            "-nostdin",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            "-rf64",
            "auto",
            "-progress",
            "pipe:1",
            "-nostats",
            "-loglevel",
            "error",
            str(output_path),
        ]
        self._run_streaming_progress(
            command, duration, cancel_event, progress_callback, "音频提取失败"
        )

    def detect_silence(
        self,
        audio_path: Path,
        duration: float,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback | None = None,
    ) -> list[tuple[float, float]]:
        command = [
            str(self.ffmpeg),
            "-nostdin",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-35dB:d=0.5",
            "-f",
            "null",
            "-",
            "-progress",
            "pipe:1",
            "-nostats",
            "-loglevel",
            "info",
        ]
        lines: list[str] = []
        self._run_streaming_progress(
            command,
            duration,
            cancel_event,
            progress_callback or (lambda _value: None),
            "静音检测失败",
            collected_lines=lines,
        )
        intervals: list[tuple[float, float]] = []
        pending_start: float | None = None
        for line in lines:
            start_match = _SILENCE_START.search(line)
            if start_match:
                pending_start = float(start_match.group(1))
            end_match = _SILENCE_END.search(line)
            if end_match:
                end = float(end_match.group(1))
                start = pending_start if pending_start is not None else max(0.0, end - 0.5)
                if end >= start:
                    intervals.append((start, min(end, duration)))
                pending_start = None
        if pending_start is not None and pending_start < duration:
            intervals.append((pending_start, duration))
        return intervals

    def create_chunk(
        self,
        audio_path: Path,
        output_path: Path,
        start: float,
        duration: float,
        cancel_event: threading.Event,
    ) -> None:
        codec_options = (
            ["-c:a", "pcm_s16le"]
            if output_path.suffix.lower() == ".wav"
            else ["-c:a", "flac", "-compression_level", "5"]
        )
        command = [
            str(self.ffmpeg),
            "-y",
            "-nostdin",
            "-ss",
            f"{start:.3f}",
            "-i",
            str(audio_path),
            "-t",
            f"{duration:.3f}",
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            *codec_options,
            "-progress",
            "pipe:1",
            "-nostats",
            "-loglevel",
            "error",
            str(output_path),
        ]
        self._run_streaming_progress(
            command, duration, cancel_event, lambda _value: None, "音频分段失败"
        )

    def _run_capture(
        self,
        command: list[str],
        cancel_event: threading.Event,
        error_prefix: str,
    ) -> str:
        if cancel_event.is_set():
            raise UserCancelledError("用户已取消")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            creationflags=self._creationflags,
            startupinfo=self._startupinfo,
        )
        self._set_process(process)
        try:
            if cancel_event.is_set():
                raise UserCancelledError("用户已取消")
            while True:
                try:
                    output, _ = process.communicate(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if cancel_event.is_set():
                        self._terminate_and_wait(process)
                        raise UserCancelledError("用户已取消")
            if cancel_event.is_set():
                raise UserCancelledError("用户已取消")
            if process.returncode != 0:
                summary = output.strip()[-2000:]
                raise MediaProcessingError(f"{error_prefix}：{summary}")
            return output
        finally:
            self._clear_process(process)

    def _run_streaming_progress(
        self,
        command: list[str],
        duration: float,
        cancel_event: threading.Event,
        progress_callback: ProgressCallback,
        error_prefix: str,
        *,
        collected_lines: list[str] | None = None,
    ) -> None:
        if cancel_event.is_set():
            raise UserCancelledError("用户已取消")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=self._creationflags,
            startupinfo=self._startupinfo,
        )
        self._set_process(process)
        tail: list[str] = []
        try:
            if cancel_event.is_set():
                raise UserCancelledError("用户已取消")
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if collected_lines is not None:
                    collected_lines.append(line)
                tail.append(line)
                if len(tail) > 80:
                    tail.pop(0)
                if cancel_event.is_set():
                    self._terminate_and_wait(process)
                    raise UserCancelledError("用户已取消")
                if line.startswith("out_time_ms="):
                    try:
                        elapsed = float(line.partition("=")[2]) / 1_000_000.0
                        progress_callback(min(1.0, elapsed / max(duration, 0.001)))
                    except ValueError:
                        pass
            return_code = process.wait()
            if cancel_event.is_set():
                raise UserCancelledError("用户已取消")
            if return_code != 0:
                raise MediaProcessingError(f"{error_prefix}：{' | '.join(tail[-12:])}")
            progress_callback(1.0)
        finally:
            self._clear_process(process)

    def _set_process(self, process: subprocess.Popen[str]) -> None:
        with self._process_lock:
            self._process = process

    def _clear_process(self, process: subprocess.Popen[str]) -> None:
        try:
            self._terminate_and_wait(process)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            with self._process_lock:
                if self._process is process:
                    self._process = None

    @staticmethod
    def _terminate_and_wait(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
