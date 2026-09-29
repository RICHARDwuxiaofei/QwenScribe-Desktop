"""Crash-isolated client for the CUDA Forced Aligner."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Callable

from .gal_alignment import Unit
from .model_catalog import find_installed_model, FORCED_ALIGNER_MODEL_ID

LOGGER = logging.getLogger(__name__)


class ForcedAlignerError(RuntimeError):
    pass


class ForcedAlignerService:
    def __init__(self, application_directory: Path | None = None, device_index: int = 0, align_fn: Callable | None = None, device: str | None = None):
        self.application_directory = Path(application_directory or Path.cwd())
        self.device_index = device_index
        self.device = device or f"cuda:{device_index}"
        self._align_fn = align_fn
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._loaded = False

    @property
    def model_available(self) -> bool:
        return find_installed_model("forced_aligner", self.application_directory) is not None

    def load(self) -> None:
        if self._align_fn:
            self._loaded = True
            return
        if self._loaded:
            return
        source = find_installed_model("forced_aligner", self.application_directory)
        if source is None:
            raise ForcedAlignerError(f"缺少 {FORCED_ALIGNER_MODEL_ID}；请在 Gal 页面下载模型，或设置 QWEN_FORCED_ALIGNER_MODEL_PATH")
        self._request("load", model_source=str(source), device=self.device)
        self._loaded = True

    def align(self, audio: Path, text: str, language: str) -> list[Unit]:
        if not self._loaded:
            self.load()
        if self._align_fn:
            return self._align_fn(audio, text, language)
        response = self._request("align", audio=str(audio.resolve()), text=text, language=language)
        return [Unit(**item) for item in response["units"]]

    def clear_cache(self) -> None:
        if self._process and self._process.poll() is None:
            self._request("clear_cache")

    def close(self) -> None:
        process = self._process
        self._process = None
        self._loaded = False
        if process and process.poll() is None:
            try:
                self._send(process, {"command": "close"})
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)

    def cancel(self) -> None:
        process = self._process
        self._process = None
        self._loaded = False
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=5)

    def _request(self, command: str, **payload):
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                args = [sys.executable, "--forced-aligner-worker"] if getattr(sys, "frozen", False) else [sys.executable, "-u", "-m", "src.forced_aligner_worker"]
                self._process = subprocess.Popen(args, cwd=self.application_directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
                threading.Thread(target=self._drain_stderr, args=(self._process,), name="qwen-aligner-stderr", daemon=True).start()
            return self._send(self._process, {"command": command, **payload})

    @staticmethod
    def _drain_stderr(process):
        for line in process.stderr:
            LOGGER.info("[Forced Aligner 子进程] %s", line.rstrip())

    def _send(self, process, request):
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
            line = process.stdout.readline()
        except (OSError, AttributeError) as error:
            raise ForcedAlignerError(f"Forced Aligner 子进程通信失败：{error}") from error
        if not line:
            self._loaded = False
            raise ForcedAlignerError(f"Forced Aligner 子进程异常退出（exit={process.poll()}）")
        response = json.loads(line)
        if not response.get("ok"):
            category = response.get("error_type")
            raise ForcedAlignerError(("CUDA OOM：" if category == "cuda_oom" else "Forced Aligner 失败：") + str(response.get("message")))
        return response.get("result", {})
