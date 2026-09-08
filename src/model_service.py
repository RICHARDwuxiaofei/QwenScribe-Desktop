"""Lazy, persistent Qwen3-ASR Transformers backend wrapper."""

from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .exceptions import ModelLoadError, TranscriptionError
from .model_catalog import find_installed_model


LOGGER = logging.getLogger(__name__)
DEFAULT_MODEL_ID = "Qwen/Qwen3-ASR-1.7B"
@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    text: str
    language: str | None


class RemoteOutOfMemoryError(RuntimeError):
    """CUDA OOM reported by the isolated Transformers process."""


class ModelService:
    """Persistent Transformers service, isolated from the Qt process in production."""

    def __init__(
        self,
        *,
        application_directory: Path | None = None,
        device_index: int = 0,
        model_factory: Callable[..., Any] | None = None,
        torch_module: Any | None = None,
    ) -> None:
        self.application_directory = Path(application_directory or Path.cwd())
        self.device_index = device_index
        self._model_factory = model_factory
        self._torch = torch_module
        self._model: Any | None = None
        self._loaded = False
        self._process: subprocess.Popen[str] | None = None
        self._request_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None
        self._use_subprocess = model_factory is None and torch_module is None

    @property
    def is_loaded(self) -> bool:
        if self._use_subprocess:
            if self._process is None or self._process.poll() is not None:
                self._loaded = False
            return self._loaded
        return self._model is not None

    @property
    def chunk_suffix(self) -> str:
        return ".flac"

    @property
    def model_source(self) -> str:
        installed = find_installed_model("transformers", self.application_directory)
        return str(installed) if installed is not None else DEFAULT_MODEL_ID

    @property
    def model_available(self) -> bool:
        return find_installed_model("transformers", self.application_directory) is not None

    def gpu_information(self) -> tuple[bool, str]:
        """Return CUDA readiness and a concise user-facing device description."""
        try:
            torch = self._get_torch()
            if not torch.cuda.is_available():
                return False, "CUDA 不可用。请安装 CUDA 版 PyTorch；第一版不支持 CPU 回退。"
            device_count = int(getattr(torch.cuda, "device_count", lambda: 1)())
            if self.device_index < 0 or self.device_index >= device_count:
                return False, f"CUDA 设备 cuda:{self.device_index} 当前不可用。"
            properties = torch.cuda.get_device_properties(self.device_index)
            total_gib = float(properties.total_memory) / (1024.0**3)
            return True, (
                f"CUDA cuda:{self.device_index}：{properties.name}"
                f"（{total_gib:.1f} GB 显存）"
            )
        except Exception as error:
            LOGGER.exception("检测 CUDA 设备失败")
            return False, f"CUDA 检测失败：{error}"

    def load(self) -> None:
        if self.is_loaded:
            return
        if self._use_subprocess:
            try:
                if not self.model_available:
                    raise ModelLoadError("尚未安装 Qwen3-ASR-1.7B Transformers 模型")
                response = self._request(
                    "load",
                    model_source=self.model_source,
                    device_index=self.device_index,
                )
                self._loaded = True
                LOGGER.info("隔离进程中的 Transformers 模型加载完成：%s", response)
                return
            except ModelLoadError:
                raise
            except Exception as error:
                raise ModelLoadError(f"模型加载失败：{error}") from error
        try:
            torch = self._get_torch()
            if not torch.cuda.is_available():
                raise ModelLoadError("CUDA 不可用，第一版不支持 CPU 回退")
            factory = self._model_factory
            if factory is None:
                if not self.model_available:
                    raise ModelLoadError("尚未安装 Qwen3-ASR-1.7B Transformers 模型")
                LOGGER.info("正在导入 qwen_asr Transformers 后端")
                from qwen_asr import Qwen3ASRModel

                LOGGER.info("qwen_asr Transformers 后端导入完成")
                factory = Qwen3ASRModel.from_pretrained
            device_count = int(getattr(torch.cuda, "device_count", lambda: 1)())
            if self.device_index < 0 or self.device_index >= device_count:
                raise ModelLoadError(f"CUDA 设备 cuda:{self.device_index} 当前不可用")
            device = f"cuda:{self.device_index}"
            LOGGER.info("正在根据 %s 设备属性选择推理精度", device)
            dtype = self._preferred_cuda_dtype(torch, self.device_index)
            LOGGER.info("加载模型 %s，dtype=%s，device=%s", self.model_source, dtype, device)
            self._model = factory(
                self.model_source,
                dtype=dtype,
                device_map=device,
                max_inference_batch_size=1,
                max_new_tokens=2048,
            )
            LOGGER.info("模型加载完成")
        except ModelLoadError:
            raise
        except Exception as error:
            LOGGER.exception("模型加载失败")
            raise ModelLoadError(f"模型加载失败：{error}") from error

    @staticmethod
    def _preferred_cuda_dtype(torch: Any, device_index: int = 0) -> Any:
        """Select BF16 without torch.cuda.current_device() in a Qt worker thread.

        torch.cuda.is_bf16_supported() calls current_device() internally.  On
        Windows, PyTorch 2.11 can access-violate there when invoked from a
        long-lived QThread even though an explicit cuda:0 query is healthy.
        NVIDIA devices with compute capability 8.0 or newer support BF16.
        """
        properties = torch.cuda.get_device_properties(device_index)
        major = int(getattr(properties, "major", 0))
        return torch.bfloat16 if major >= 8 else torch.float16

    def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        if self._use_subprocess:
            if not self.is_loaded:
                raise TranscriptionError("模型尚未加载")
            try:
                response = self._request(
                    "transcribe", audio=str(audio_path.resolve()), language=language
                )
                return TranscriptionResult(
                    text=str(response.get("text", "")).strip(),
                    language=response.get("language"),
                )
            except RemoteOutOfMemoryError:
                raise
            except Exception as error:
                if isinstance(error, TranscriptionError):
                    raise
                raise TranscriptionError(f"模型识别失败：{error}") from error
        if self._model is None:
            raise TranscriptionError("模型尚未加载")
        torch = self._get_torch()
        try:
            with torch.inference_mode():
                results = self._model.transcribe(audio=str(audio_path), language=language)
            if not results:
                raise TranscriptionError("模型没有返回识别结果")
            first = results[0]
            return TranscriptionResult(
                text=str(getattr(first, "text", "")).strip(),
                language=getattr(first, "language", None),
            )
        except Exception as error:
            if self.is_out_of_memory(error) or isinstance(error, TranscriptionError):
                raise
            raise TranscriptionError(f"模型识别失败：{error}") from error

    def is_out_of_memory(self, error: BaseException) -> bool:
        if isinstance(error, RemoteOutOfMemoryError):
            return True
        torch = self._get_torch()
        oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
        return bool(oom_type and isinstance(error, oom_type))

    def clear_cuda_cache(self) -> None:
        gc.collect()
        if self._use_subprocess:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._request("clear_cache")
                except Exception:
                    LOGGER.exception("隔离模型进程清理 CUDA 缓存失败")
            return
        torch = self._get_torch()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _get_torch(self) -> Any:
        if self._torch is None:
            import torch

            self._torch = torch
        return self._torch

    def close(self) -> None:
        """Stop the isolated model process without affecting the GUI process."""
        process = self._process
        self._loaded = False
        self._process = None
        if process is None:
            return
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.write(json.dumps({"command": "close"}) + "\n")
                    process.stdin.flush()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def _ensure_process(self) -> subprocess.Popen[str]:
        process = self._process
        if process is not None and process.poll() is None:
            return process
        if process is not None:
            self._loaded = False
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--transformers-worker"]
        else:
            command = [sys.executable, "-u", "-m", "src.transformers_worker"]
        LOGGER.info("启动隔离 Transformers 模型进程：%s", command)
        process = subprocess.Popen(
            command,
            cwd=str(self.application_directory),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creation_flags,
        )
        self._process = process
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process,),
            name="qwen-transformers-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        return process

    @staticmethod
    def _drain_stderr(process: subprocess.Popen[str]) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            message = line.rstrip()
            if message:
                LOGGER.info("[Transformers 子进程] %s", message)

    def _request(self, command: str, **payload: Any) -> dict[str, Any]:
        with self._request_lock:
            process = self._ensure_process()
            if process.stdin is None or process.stdout is None:
                raise ModelLoadError("无法连接 Transformers 模型子进程")
            try:
                process.stdin.write(
                    json.dumps({"command": command, **payload}, ensure_ascii=False) + "\n"
                )
                process.stdin.flush()
                line = process.stdout.readline()
            except (BrokenPipeError, OSError) as error:
                line = ""
                LOGGER.error("Transformers 子进程通信失败", exc_info=True)
            if not line:
                exit_code = process.poll()
                self._loaded = False
                self._process = None
                raise ModelLoadError(
                    "Transformers 模型子进程异常退出"
                    + (f"（退出码 {exit_code}）" if exit_code is not None else "")
                    + "；主界面已受到保护，请重试或切换 Vulkan 后端"
                )
            try:
                response = json.loads(line)
            except json.JSONDecodeError as error:
                raise ModelLoadError(f"模型子进程返回了无效响应：{line[:200]}") from error
            if response.get("ok") is True:
                result = response.get("result", {})
                return result if isinstance(result, dict) else {}
            error_type = str(response.get("error_type", "error"))
            message = str(response.get("message", "模型子进程执行失败"))
            if error_type == "cuda_oom":
                raise RemoteOutOfMemoryError(message)
            if command == "load":
                raise ModelLoadError(message)
            raise TranscriptionError(message)
