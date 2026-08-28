"""Persistent Qt worker coordinating one transcription task at a time."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from PySide6.QtCore import QObject, Signal, Slot

from .exceptions import (
    QwenASRDesktopError,
    TranscriptionError,
    UserCancelledError,
)
from .media_service import MediaService
from .model_service import ModelService, TranscriptionResult
from .segmenter import Segment, calculate_segments
from .utils import (
    append_partial,
    choose_output_path,
    create_task_temp_directory,
    partial_path_for,
    reservation_path_for,
)


LOGGER = logging.getLogger(__name__)
MIN_OOM_SEGMENT_SECONDS = 30.0
MAX_OOM_SPLIT_DEPTH = 4


@dataclass(frozen=True, slots=True)
class TranscriptionTask:
    input_path: Path
    output_directory: Path
    language: str | None


class TranscriptionWorker(QObject):
    """Run all expensive work in one persistent QThread."""

    status_changed = Signal(str)
    progress_changed = Signal(int)
    user_log = Signal(str)
    language_detected = Signal(str)
    task_started = Signal()
    task_completed = Signal(str)
    task_cancelled = Signal(str)
    task_failed = Signal(str, str)
    gpu_info_ready = Signal(bool, str)
    devices_discovered = Signal(object, object)

    def __init__(
        self,
        application_directory: Path,
        model_service: Any | None = None,
    ) -> None:
        super().__init__()
        self._application_directory = Path(application_directory)
        self._model_service = model_service or ModelService()
        self._media_service: MediaService | None = None
        self._cancel_event = threading.Event()
        self._busy_lock = threading.Lock()
        self._busy = False
        self._task_pending = False
        self._pending_cancel = False
        self._chunk_serial = 0
        self._full_audio_path: Path | None = None
        self._task_temp_directory: Path | None = None
        self._partial_handle: TextIO | None = None
        self._has_previous_text = False
        self._completed_duration = 0.0
        self._total_duration = 1.0

    @property
    def is_busy(self) -> bool:
        with self._busy_lock:
            return self._busy

    def request_cancel(self) -> None:
        """Thread-safe cancellation entry point called directly by the GUI thread."""
        with self._busy_lock:
            if self._busy:
                self._cancel_event.set()
            elif self._task_pending:
                # Covers the narrow window after the GUI queues start_task but
                # before the worker thread enters the slot.
                self._pending_cancel = True
        media_service = self._media_service
        if media_service is not None:
            media_service.cancel_current_process()

    def mark_task_pending(self) -> None:
        """Mark a task before its queued Qt signal crosses to the worker thread."""
        with self._busy_lock:
            self._task_pending = True
            self._pending_cancel = False

    @Slot()
    def detect_gpu(self) -> None:
        available, description = self._model_service.gpu_information()
        self.gpu_info_ready.emit(available, description)

    @Slot()
    def discover_devices(self) -> None:
        """Enumerate every CUDA/Vulkan device without blocking the Qt GUI."""
        cuda_devices: list[tuple[str, str]] = []
        vulkan_devices: list[tuple[str, str]] = []
        try:
            import torch

            if torch.cuda.is_available():
                for index in range(torch.cuda.device_count()):
                    properties = torch.cuda.get_device_properties(index)
                    total_gib = float(properties.total_memory) / (1024.0**3)
                    cuda_devices.append(
                        (
                            f"cuda:{index}",
                            f"CUDA cuda:{index}：{properties.name}（{total_gib:.1f} GB）",
                        )
                    )
        except Exception:
            LOGGER.exception("后台枚举 CUDA 设备失败")

        discovery_service = None
        try:
            from .vulkan_model_service import VulkanModelService

            discovery_service = VulkanModelService(
                self._application_directory, device_id="auto"
            )
            vulkan_devices = [
                (device.device_id, device.display_label)
                for device in discovery_service.discover_devices()
            ]
        except Exception:
            LOGGER.exception("后台枚举 Vulkan 设备失败")
        finally:
            if discovery_service is not None:
                discovery_service.close()
        self.devices_discovered.emit(cuda_devices, vulkan_devices)

    @Slot()
    def shutdown_backend(self) -> None:
        close = getattr(self._model_service, "close", None)
        if callable(close):
            close()

    @Slot(object)
    def start_task(self, task: TranscriptionTask) -> None:
        with self._busy_lock:
            if self._busy:
                self.task_failed.emit("已有转写任务正在运行", "")
                return
            self._busy = True
            self._task_pending = False
            cancelled_before_start = self._pending_cancel
            self._pending_cancel = False
        if cancelled_before_start:
            self._cancel_event.set()
        else:
            self._cancel_event.clear()
        self.task_started.emit()
        self.progress_changed.emit(0)

        partial_path: Path | None = None
        final_path: Path | None = None
        reservation_path: Path | None = None
        completed_successfully = False
        try:
            self._check_cancelled()
            self._media_service = self._media_service or MediaService(
                self._application_directory
            )
            self._check_cancelled()
            task.output_directory.mkdir(parents=True, exist_ok=True)
            final_path, partial_path, reservation_path = self._reserve_output(task)
            self._task_temp_directory = create_task_temp_directory()
            self._full_audio_path = self._task_temp_directory / "source.wav"

            with partial_path.open("x", encoding="utf-8", newline="\n") as partial_handle:
                self._partial_handle = partial_handle
                self._has_previous_text = False
                self._execute_task(task)
            self._partial_handle = None
            self._set_status("正在保存文本")
            self.progress_changed.emit(98)
            if final_path.exists():
                raise TranscriptionError(
                    f"输出文件在转写期间被其他程序创建，已保留部分结果：{partial_path}"
                )
            os.replace(partial_path, final_path)
            completed_successfully = True
            self.progress_changed.emit(100)
            self._set_status("已完成")
            self.user_log.emit(f"转写完成：{final_path}")
            self.task_completed.emit(str(final_path))
        except UserCancelledError:
            self._set_status("已取消")
            retained = str(partial_path) if partial_path and partial_path.exists() else ""
            if retained:
                self.user_log.emit(f"已取消，已识别内容保存在：{retained}")
            else:
                self.user_log.emit("已取消，尚未生成部分文本")
            self.task_cancelled.emit(retained)
        except Exception as error:
            LOGGER.error("转写任务失败\n%s", traceback.format_exc())
            self._set_status("发生错误")
            retained = str(partial_path) if partial_path and partial_path.exists() else ""
            summary = self._user_error_message(error)
            if retained:
                summary = f"{summary}\n已保留部分结果：{retained}"
            self.user_log.emit(summary)
            self.task_failed.emit(summary, retained)
        finally:
            self._partial_handle = None
            if reservation_path is not None:
                try:
                    reservation_path.unlink(missing_ok=True)
                except OSError:
                    LOGGER.exception("无法删除输出路径预留标记 %s", reservation_path)
            if not completed_successfully and final_path is not None:
                # A final file is never intentionally created before success.
                LOGGER.info("任务未完成，最终输出未生成：%s", final_path)
            if self._task_temp_directory is not None:
                try:
                    shutil.rmtree(self._task_temp_directory)
                except OSError:
                    LOGGER.exception("无法清理任务临时目录 %s", self._task_temp_directory)
            self._full_audio_path = None
            self._task_temp_directory = None
            with self._busy_lock:
                self._busy = False
                self._task_pending = False
                self._pending_cancel = False

    def _execute_task(self, task: TranscriptionTask) -> None:
        assert self._media_service is not None
        assert self._full_audio_path is not None

        self._set_status("正在检查文件")
        self.user_log.emit("正在检查输入文件和音频轨道…")
        media_info = self._media_service.probe(task.input_path, self._cancel_event)
        self.progress_changed.emit(5)

        self._set_status("正在提取音频")
        self.user_log.emit("正在提取 16 kHz 单声道音频…")
        self._media_service.extract_audio(
            task.input_path,
            self._full_audio_path,
            media_info.duration,
            self._cancel_event,
            lambda ratio: self.progress_changed.emit(5 + round(10 * ratio)),
        )

        # Container-less formats such as ADTS AAC may only expose an estimated
        # duration based on bitrate.  That estimate can be substantially wrong
        # for VBR recordings.  The extracted PCM WAV has an exact duration, so
        # it must be the source of truth for silence detection and chunk bounds.
        extracted_info = self._media_service.probe(
            self._full_audio_path, self._cancel_event
        )
        audio_duration = extracted_info.duration
        duration_delta = abs(audio_duration - media_info.duration)
        if duration_delta > max(1.0, audio_duration * 0.01):
            LOGGER.warning(
                "输入媒体报告时长 %.3fs，与提取音频时长 %.3fs 不一致；"
                "后续使用提取音频时长",
                media_info.duration,
                audio_duration,
            )
            self.user_log.emit(
                "输入格式的时长估算不准确，已按提取音频的实际时长处理。"
            )

        self._set_status("正在检测静音")
        self.user_log.emit("正在检测静音并计算分段…")
        silence_intervals = self._media_service.detect_silence(
            self._full_audio_path,
            audio_duration,
            self._cancel_event,
            lambda ratio: self.progress_changed.emit(15 + round(3 * ratio)),
        )
        segments = calculate_segments(audio_duration, silence_intervals)
        if not segments:
            raise TranscriptionError("没有可识别的音频区间")
        LOGGER.info(
            "媒体时长 %.3fs，静音区间 %d 个，初始分段 %d 个",
            audio_duration,
            len(silence_intervals),
            len(segments),
        )
        self.progress_changed.emit(18)
        self._check_cancelled()

        if not self._model_service.is_loaded:
            self._set_status("正在加载模型")
            self.user_log.emit("正在加载 Qwen3-ASR-1.7B；首次运行可能需要下载数 GB 文件…")
            self._model_service.load()
        else:
            self.user_log.emit("正在复用已加载的模型…")
        self.progress_changed.emit(23)

        self._completed_duration = 0.0
        self._total_duration = sum(segment.duration for segment in segments)
        for index, segment in enumerate(segments, start=1):
            self._check_cancelled()
            self._set_status(f"正在识别第 {index}/{len(segments)} 段")
            self._process_segment(
                segment,
                task.language,
                initial_index=index,
                initial_count=len(segments),
                split_depth=0,
            )
        self.progress_changed.emit(97)

    def _process_segment(
        self,
        segment: Segment,
        language: str | None,
        *,
        initial_index: int,
        initial_count: int,
        split_depth: int,
    ) -> None:
        assert self._media_service is not None
        assert self._full_audio_path is not None
        assert self._task_temp_directory is not None
        assert self._partial_handle is not None
        self._check_cancelled()
        self._chunk_serial += 1
        chunk_suffix = str(getattr(self._model_service, "chunk_suffix", ".flac"))
        if chunk_suffix not in {".flac", ".wav"}:
            raise TranscriptionError(f"模型服务声明了不支持的片段格式：{chunk_suffix}")
        chunk_path = self._task_temp_directory / (
            f"chunk_{self._chunk_serial:05d}{chunk_suffix}"
        )
        try:
            self._media_service.create_chunk(
                self._full_audio_path,
                chunk_path,
                segment.start,
                segment.duration,
                self._cancel_event,
            )
            result = self._transcribe_with_retry(chunk_path, language)
        except Exception as error:
            if self._model_service.is_out_of_memory(error):
                self._model_service.clear_cuda_cache()
                if (
                    split_depth >= MAX_OOM_SPLIT_DEPTH
                    or segment.duration / 2.0 < MIN_OOM_SEGMENT_SECONDS
                ):
                    raise TranscriptionError(
                        f"显存不足，片段已无法继续细分（约 {segment.duration:.1f} 秒）"
                    ) from error
                midpoint = segment.start + segment.duration / 2.0
                LOGGER.warning(
                    "片段 %.3f-%.3f 秒发生 OOM，自动二分，深度=%d",
                    segment.start,
                    segment.end,
                    split_depth + 1,
                )
                self.user_log.emit(
                    f"第 {initial_index}/{initial_count} 段显存不足，正在自动细分后重试…"
                )
                chunk_path.unlink(missing_ok=True)
                self._process_segment(
                    Segment(segment.start, midpoint),
                    language,
                    initial_index=initial_index,
                    initial_count=initial_count,
                    split_depth=split_depth + 1,
                )
                self._check_cancelled()
                self._process_segment(
                    Segment(midpoint, segment.end),
                    language,
                    initial_index=initial_index,
                    initial_count=initial_count,
                    split_depth=split_depth + 1,
                )
                return
            raise
        finally:
            try:
                chunk_path.unlink(missing_ok=True)
            except OSError:
                LOGGER.exception("无法删除临时片段 %s", chunk_path)

        self._has_previous_text = append_partial(
            self._partial_handle,
            result.text,
            has_previous_text=self._has_previous_text,
        )
        if result.language:
            self.language_detected.emit(str(result.language))
        self._completed_duration += segment.duration
        recognition_ratio = min(1.0, self._completed_duration / self._total_duration)
        self.progress_changed.emit(23 + round(74 * recognition_ratio))

    def _transcribe_with_retry(
        self, chunk_path: Path, language: str | None
    ) -> TranscriptionResult:
        last_error: Exception | None = None
        for attempt in range(2):
            self._check_cancelled()
            try:
                return self._model_service.transcribe(chunk_path, language)
            except Exception as error:
                if self._model_service.is_out_of_memory(error):
                    raise
                last_error = error
                if attempt == 0:
                    LOGGER.warning("片段识别失败，将重试一次", exc_info=True)
                    self.user_log.emit("当前片段识别失败，正在自动重试一次…")
                    self._model_service.clear_cuda_cache()
        assert last_error is not None
        raise TranscriptionError(f"片段重试后仍然失败：{last_error}") from last_error

    def _reserve_output(
        self, task: TranscriptionTask
    ) -> tuple[Path, Path, Path]:
        while True:
            final_path = choose_output_path(task.input_path, task.output_directory)
            partial_path = partial_path_for(final_path)
            reservation_path = reservation_path_for(final_path)
            try:
                with reservation_path.open("x", encoding="ascii") as marker:
                    marker.write(str(os.getpid()))
                return final_path, partial_path, reservation_path
            except FileExistsError:
                continue

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise UserCancelledError("用户已取消")

    def _set_status(self, message: str) -> None:
        self.status_changed.emit(message)
        LOGGER.info(message)

    @staticmethod
    def _user_error_message(error: Exception) -> str:
        if isinstance(error, QwenASRDesktopError):
            return str(error)
        return f"发生未预期错误：{error}"
