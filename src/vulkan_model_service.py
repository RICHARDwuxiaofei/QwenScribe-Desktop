"""Qwen3-ASR GGUF backend using the local transcribe.cpp Vulkan worker."""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Any
from uuid import uuid4

from .exceptions import ModelLoadError, TranscriptionError
from .device_discovery import DiscoveryResult
from .language_map import vulkan_language_hint
from .model_catalog import VULKAN_FILENAME, find_installed_model
from .model_service import TranscriptionResult


LOGGER = logging.getLogger(__name__)
CONTRACT_VERSION = 2
WORKER_FILENAME = "PuriPulyHeartGpuWorker.exe"
MODEL_FILENAME = VULKAN_FILENAME
MODEL_INSTALL_DIRNAME = "qwen3-asr-1.7b-q6-k-transcribe-vulkan"


@dataclass(frozen=True, slots=True)
class VulkanDevice:
    device_id: str
    registry_index: int
    name: str
    description: str
    device_type: str
    memory_total_bytes: int
    memory_free_bytes: int

    @property
    def display_label(self) -> str:
        type_label = {
            "igpu": "核显",
            "gpu": "独立显卡",
            "accel": "加速器",
            "cpu": "CPU",
        }.get(self.device_type, "其他设备")
        memory = ""
        if self.memory_total_bytes > 0:
            memory = f" · {self.memory_total_bytes / (1024 ** 3):.1f} GB"
        device_name = self.description.strip() or self.name
        return f"Vulkan：{device_name}（{type_label}{memory}）"


class VulkanWorkerError(RuntimeError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class VulkanModelService:
    """Persistent, strictly selected Vulkan Qwen3-ASR service.

    The native worker is a separate process so a Vulkan driver failure cannot
    directly corrupt the Qt/Python process.  Requests use an authenticated
    loopback-only JSON-lines contract compatible with the PuriPuly worker.
    """

    def __init__(
        self,
        application_directory: Path,
        *,
        device_id: str,
        executable_path: Path | None = None,
        model_path: Path | None = None,
    ) -> None:
        self._application_directory = Path(application_directory)
        self.device_id = device_id
        self._configured_executable = executable_path
        self._configured_model = model_path
        self._process: subprocess.Popen[bytes] | None = None
        self._server: socket.socket | None = None
        self._connection: socket.socket | None = None
        self._stream: BinaryIO | None = None
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._session_id = ""
        self._loaded = False
        self._active_device: VulkanDevice | None = None
        self._request_lock = threading.Lock()
        self._stderr_thread: threading.Thread | None = None
        self._discovery_details: dict[str, Any] = {}
        self.actual_backend: str | None = None

    @property
    def is_loaded(self) -> bool:
        if self._process is None or self._process.poll() is not None:
            self._loaded = False
            self._active_device = None
        return self._loaded

    @property
    def chunk_suffix(self) -> str:
        return ".wav"

    @property
    def model_source(self) -> str:
        return str(self._resolve_model_path())

    @property
    def model_available(self) -> bool:
        return find_installed_model("vulkan", self._application_directory) is not None

    @property
    def active_device(self) -> VulkanDevice | None:
        return self._active_device

    def gpu_information(self) -> tuple[bool, str]:
        try:
            devices = self.discover_devices()
            selected = self._select_device(devices)
            return True, selected.display_label
        except Exception as error:
            LOGGER.exception("Vulkan 设备检测失败")
            return False, f"Vulkan 核显后端不可用：{self._friendly_error(error)}"

    def discover_devices(self) -> tuple[VulkanDevice, ...]:
        self._ensure_worker()
        payload = self._request("discover", timeout=20.0)
        diagnostic = payload.get("diagnostic")
        self._discovery_details = diagnostic if isinstance(diagnostic, dict) else {}
        LOGGER.info("Vulkan discovery diagnostic: %s", self._discovery_details)
        if self._discovery_details.get("error"):
            error = self._discovery_details["error"]
            if not isinstance(error, dict) or not isinstance(error.get("code"), str):
                raise VulkanWorkerError("discovery_invalid")
            raise VulkanWorkerError(error["code"], self._discovery_details)
        raw_devices = payload.get("devices")
        if not isinstance(raw_devices, list):
            raise VulkanWorkerError("discovery_invalid")
        devices = tuple(self._device_from_payload(item) for item in raw_devices)
        return devices

    def discover_result(self) -> DiscoveryResult:
        try:
            devices = self.discover_devices()
            return DiscoveryResult("vulkan", tuple((d.device_id, d.display_label) for d in devices),
                                   details=self._discovery_details)
        except Exception as error:
            LOGGER.exception("Vulkan discovery failed: %s", getattr(error, "details", {}))
            code = error.code if isinstance(error, VulkanWorkerError) else "discovery_exception"
            return DiscoveryResult("vulkan", ok=False, error_code=code,
                                   error_message=self._friendly_error(error),
                                   details={"exception": repr(error), **getattr(error, "details", {})})

    @staticmethod
    def _drain_stderr(stream: BinaryIO) -> None:
        # Bounded reads also drain native messages without newlines. Application
        # logging rotates this output; launch manifests and tokens are not logged.
        try:
            while chunk := stream.read1(4096):
                LOGGER.warning("Vulkan worker stderr: %s", chunk.decode("utf-8", errors="replace"))
        finally:
            stream.close()

    def load(self) -> None:
        if self.is_loaded:
            return
        try:
            devices = self.discover_devices()
            requested = self._select_device(devices)
            model_path = self._resolve_model_path()
            if not model_path.is_file():
                raise ModelLoadError(f"Vulkan 1.7B GGUF 模型不存在：{model_path}")
            payload = self._request(
                "activate",
                timeout=240.0,
                model_path=str(model_path.resolve()),
                device_id=self.device_id,
            )
            activation = payload.get("activation")
            if not isinstance(activation, dict):
                raise VulkanWorkerError("activation_invalid")
            actual_backend = activation.get("actual_backend")
            if not isinstance(actual_backend, str) or not actual_backend.lower().startswith("vulkan"):
                self.close()
                raise VulkanWorkerError("strict_vulkan_rejected")
            self.actual_backend = actual_backend
            raw_device = activation.get("device")
            active = self._device_from_payload(raw_device)
            if self.device_id != "auto" and active.device_id != requested.device_id:
                self.close()
                raise ModelLoadError(
                    "Vulkan 实际启用设备与所选设备不一致，已停止以避免静默回退"
                )
            self._active_device = active
            self._loaded = True
            LOGGER.info(
                "Vulkan 模型加载完成：device_id=%s name=%s model=%s load=%s warmup=%s",
                active.device_id,
                active.name,
                model_path,
                activation.get("model_load_seconds"),
                activation.get("warmup_seconds"),
            )
        except ModelLoadError:
            raise
        except Exception as error:
            LOGGER.exception("Vulkan 模型加载失败")
            raise ModelLoadError(
                f"Vulkan 模型加载失败：{self._friendly_error(error)}"
            ) from error

    def transcribe(self, audio_path: Path, language: str | None) -> TranscriptionResult:
        if not self.is_loaded:
            raise TranscriptionError("Vulkan 模型尚未加载")
        if audio_path.suffix.lower() != ".wav":
            raise TranscriptionError("Vulkan worker 仅接受 16 kHz 单声道 PCM WAV 片段")
        try:
            payload = self._request(
                "transcribe",
                timeout=900.0,
                channel="self",
                audio_path=str(audio_path.resolve()),
                language_hint=vulkan_language_hint(language),
            )
            raw = payload.get("transcription")
            if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
                raise VulkanWorkerError("transcription_invalid")
            detected = raw.get("detected_language")
            return TranscriptionResult(
                text=str(raw["text"]).strip(),
                language=str(detected) if isinstance(detected, str) else None,
            )
        except VulkanWorkerError as error:
            if self.is_out_of_memory(error):
                raise
            raise TranscriptionError(
                f"Vulkan 模型识别失败：{self._friendly_error(error)}"
            ) from error
        except Exception as error:
            raise TranscriptionError(
                f"Vulkan 模型识别失败：{self._friendly_error(error)}"
            ) from error

    @staticmethod
    def is_out_of_memory(error: BaseException) -> bool:
        return isinstance(error, VulkanWorkerError) and error.code == "out_of_memory"

    @staticmethod
    def clear_cuda_cache() -> None:
        # Vulkan/transcribe.cpp owns its allocations in the worker process.
        return

    def close(self) -> None:
        stream = self._stream
        process = self._process
        if stream is not None and process is not None and process.poll() is None:
            try:
                self._request("shutdown", timeout=3.0)
            except Exception:
                LOGGER.debug("Vulkan worker 未正常响应关闭请求", exc_info=True)
        self._dispose_worker()

    def _dispose_worker(self) -> None:
        """Release a broken session without sending another protocol request."""
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2.0)
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=2.0)
            self._stderr_thread = None
        for resource in (self._stream, self._connection, self._server):
            if resource is not None:
                try:
                    resource.close()
                except OSError:
                    pass
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()
        self._process = None
        self._server = None
        self._connection = None
        self._stream = None
        self._temporary_directory = None
        self._loaded = False
        self._active_device = None
        self.actual_backend = None

    def _ensure_worker(self) -> None:
        if self._process is not None and self._process.poll() is None and self._stream is not None:
            return
        self._dispose_worker()
        executable = self._resolve_executable_path()
        if not executable.is_file():
            raise VulkanWorkerError("worker_missing", {"path": str(executable)})
        if os.name == "nt":
            import ctypes

            try:
                ctypes.WinDLL("vulkan-1.dll", winmode=0x00000800)
            except OSError as error:
                raise VulkanWorkerError("loader_unavailable", {"exception": repr(error)}) from error
        self._session_id = uuid4().hex
        auth_token = secrets.token_hex(32)
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="qwen-asr-vulkan-worker-"
        )
        config_path = Path(self._temporary_directory.name) / "launch.json"
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(15.0)
        self._server = server
        config = {
            "contract_version": CONTRACT_VERSION,
            "session_id": self._session_id,
            "auth_token": auth_token,
            "connect_host": "127.0.0.1",
            "connect_port": int(server.getsockname()[1]),
            "heartbeat_interval_ms": 500,
            "mode": "persistent",
        }
        config_path.write_text(
            json.dumps(config, ensure_ascii=True, separators=(",", ":")),
            encoding="utf-8",
        )
        startup_info = None
        if os.name == "nt":
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = subprocess.SW_HIDE
        try:
            self._process = subprocess.Popen(
                [str(executable), "--config", str(config_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                shell=False,
                startupinfo=startup_info,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            assert self._process.stderr is not None
            self._stderr_thread = threading.Thread(target=self._drain_stderr,
                                                   args=(self._process.stderr,), daemon=True)
            self._stderr_thread.start()
            deadline = time.monotonic() + 15.0
            server.settimeout(0.2)
            while True:
                exit_code = self._process.poll()
                if exit_code is not None:
                    raise VulkanWorkerError("worker_startup_failed", {"exit_code": exit_code})
                try:
                    connection, _address = server.accept()
                    break
                except socket.timeout:
                    if time.monotonic() >= deadline:
                        raise VulkanWorkerError("worker_startup_timeout")
            connection.settimeout(30.0)
            self._connection = connection
            self._stream = connection.makefile("rwb", buffering=0)
            frame = self._read_frame()
            if not (
                frame.get("type") == "authenticate"
                and frame.get("contract_version") == CONTRACT_VERSION
                and frame.get("session_id") == self._session_id
                and secrets.compare_digest(str(frame.get("auth_token", "")), auth_token)
            ):
                raise VulkanWorkerError("authentication_failed")
        except Exception as error:
            self._dispose_worker()
            if isinstance(error, VulkanWorkerError):
                raise
            raise VulkanWorkerError("worker_startup_failed", {"exception": repr(error)}) from error

    def _request(self, request_type: str, *, timeout: float, **fields: Any) -> dict[str, Any]:
        with self._request_lock:
            self._ensure_worker()
            assert self._connection is not None
            assert self._stream is not None
            request_id = uuid4().hex
            request = {
                "type": request_type,
                "contract_version": CONTRACT_VERSION,
                "session_id": self._session_id,
                "request_id": request_id,
                **fields,
            }
            deadline = time.monotonic() + timeout
            try:
                self._connection.settimeout(timeout)
                encoded = json.dumps(request, ensure_ascii=True, separators=(",", ":"))
                self._stream.write(encoded.encode("utf-8") + b"\n")
                self._stream.flush()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError(f"Vulkan {request_type} 请求超时")
                    self._connection.settimeout(remaining)
                    frame = self._read_frame()
                    if frame.get("type") in {"heartbeat", "event"}:
                        continue
                    if frame.get("contract_version") != CONTRACT_VERSION or frame.get("session_id") != self._session_id:
                        raise VulkanWorkerError("protocol_invalid")
                    if frame.get("type") == "response" and frame.get("request_id") == request_id:
                        break
            except (OSError, VulkanWorkerError):
                # A timed-out or broken stream cannot be reused safely. The next
                # task must activate a fresh worker instead of reusing stale state.
                self._dispose_worker()
                raise
            if frame.get("status") != "ok":
                details = frame.get("payload")
                raise VulkanWorkerError(
                    str(frame.get("error_code", "worker_failure")),
                    details if isinstance(details, dict) else {},
                )
            payload = frame.get("payload")
            if not isinstance(payload, dict):
                raise VulkanWorkerError("response_invalid")
            return payload

    def _read_frame(self) -> dict[str, Any]:
        if self._stream is None:
            raise VulkanWorkerError("worker_closed")
        raw = self._stream.readline(4 * 1024 * 1024 + 1)
        if not raw:
            code = self._process.poll() if self._process is not None else None
            raise VulkanWorkerError(f"worker_closed_{code}")
        if len(raw) > 4 * 1024 * 1024:
            raise VulkanWorkerError("frame_too_large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise VulkanWorkerError("protocol_invalid") from error
        if not isinstance(payload, dict):
            raise VulkanWorkerError("protocol_invalid")
        return payload

    def _select_device(self, devices: tuple[VulkanDevice, ...]) -> VulkanDevice:
        if self.device_id == "auto":
            if not devices:
                raise VulkanWorkerError("no_devices")
            return devices[0]
        for device in devices:
            if device.device_id == self.device_id:
                return device
        raise VulkanWorkerError("device_unavailable")

    def _resolve_executable_path(self) -> Path:
        configured = os.environ.get("QWEN_ASR_VULKAN_WORKER_PATH", "").strip()
        candidates = [
            self._configured_executable,
            Path(configured).expanduser() if configured else None,
            self._application_directory / "bin" / WORKER_FILENAME,
        ]
        return next((path for path in candidates if path is not None and path.is_file()),
                    self._application_directory / "bin" / WORKER_FILENAME)

    def _resolve_model_path(self) -> Path:
        if self._configured_model is not None and self._configured_model.is_file():
            return self._configured_model
        installed = find_installed_model("vulkan", self._application_directory)
        if installed is not None:
            return installed
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        legacy = (
            local_app_data
            / "puripuly-heart"
            / "models"
            / MODEL_INSTALL_DIRNAME
            / MODEL_FILENAME
        )
        return legacy if legacy.is_file() else self._application_directory / "models" / MODEL_FILENAME

    @staticmethod
    def _device_from_payload(raw: Any) -> VulkanDevice:
        if not isinstance(raw, dict):
            raise VulkanWorkerError("device_invalid")
        try:
            return VulkanDevice(
                device_id=str(raw["device_id"]),
                registry_index=int(raw["registry_index"]),
                name=str(raw["name"]),
                description=str(raw.get("description", "")),
                device_type=str(raw.get("device_type", "unknown")),
                memory_total_bytes=int(raw.get("memory_total_bytes", 0)),
                memory_free_bytes=int(raw.get("memory_free_bytes", 0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise VulkanWorkerError("device_invalid") from error

    @staticmethod
    def _friendly_error(error: BaseException) -> str:
        if isinstance(error, VulkanWorkerError):
            if error.code.startswith("worker_closed"):
                return "worker 意外退出，请查看诊断日志"
            return {
                "unsupported_capability": "Vulkan 后端不可用，请检查显卡驱动及诊断日志",
                "backend_unavailable": "Vulkan 后端不可用，请检查显卡驱动及诊断日志",
                "backend_initialization_failed": "Vulkan 后端初始化失败，请检查显卡驱动及诊断日志",
                "loader_unavailable": "系统 Vulkan loader 不可用，请检查显卡驱动",
                "worker_missing": "找不到 Vulkan worker，请检查发行包是否完整",
                "worker_startup_failed": "worker 启动失败，请查看诊断日志",
                "worker_startup_timeout": "worker 启动超时，请查看诊断日志",
                "authentication_failed": "worker 握手认证失败",
                "protocol_invalid": "worker 协议错误",
                "device_invalid": "worker 设备数据格式错误",
                "device_index_missing": "Vulkan 设备缺少索引，请查看诊断日志",
                "discovery_invalid": "worker 设备列表格式错误",
                "response_invalid": "worker 响应格式错误",
                "no_devices": "未发现系统 Vulkan 设备，请检查显卡驱动",
                "device_unavailable": "所选 Vulkan 设备当前不可用",
                "model_missing": "GGUF 模型文件不存在",
                "model_invalid": "GGUF 模型文件无效",
                "strict_vulkan_rejected": "worker 未能以严格 Vulkan 模式启动",
                "warmup_failed": "Vulkan 模型预热失败",
                "out_of_memory": "Vulkan 设备内存不足",
                "decode_failure": "Vulkan 解码失败",
            }.get(error.code, error.code)
        return "设备检测异常，请查看诊断日志" if not isinstance(error, ModelLoadError) else str(error)
