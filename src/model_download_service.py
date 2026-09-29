"""Resumable model downloader with China and international routes."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .model_catalog import (
    BackendName,
    DownloadRegion,
    ModelFile,
    TRANSFORMERS_FILES,
    TRANSFORMERS_MODEL_ID,
    FORCED_ALIGNER_MODEL_ID,
    TRANSFORMERS_REVISION,
    VULKAN_FILENAME,
    VULKAN_REPO_ID,
    VULKAN_REVISION,
    VULKAN_SHA256,
    VULKAN_SIZE,
    download_target,
    is_complete_model,
)


LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, int, str], None]


class ModelDownloadError(RuntimeError):
    pass


class ModelDownloadCancelled(ModelDownloadError):
    pass


class ModelDownloadService:
    """Download only the files required by the selected local backend."""

    def __init__(self, *, timeout_seconds: float = 60.0) -> None:
        self.timeout_seconds = timeout_seconds

    def download(
        self,
        backend: BackendName,
        region: DownloadRegion,
        cancel_event: threading.Event,
        progress: ProgressCallback,
    ) -> Path:
        target = download_target(backend)
        if backend == "forced_aligner":
            self._check_cancel(cancel_event)
            target.mkdir(parents=True, exist_ok=True)
            try:
                if region == "china":
                    from modelscope import snapshot_download

                    snapshot_download(FORCED_ALIGNER_MODEL_ID, local_dir=str(target))
                else:
                    from huggingface_hub import snapshot_download

                    snapshot_download(FORCED_ALIGNER_MODEL_ID, local_dir=str(target))
            except ImportError as error:
                package = "modelscope" if region == "china" else "huggingface_hub"
                raise ModelDownloadError(f"缺少 {package} 下载依赖；请安装 CUDA 版依赖") from error
            except Exception as error:
                raise ModelDownloadError(f"Forced Aligner 下载失败（{region}, {target}）：{error}") from error
            self._check_cancel(cancel_event)
            if not is_complete_model(backend, target):
                raise ModelDownloadError(f"Forced Aligner 下载不完整：{target}")
            progress(1, 1, "Qwen3-ForcedAligner-0.6B")
            return target
        if backend == "transformers":
            target.mkdir(parents=True, exist_ok=True)
            total = sum(item.size_bytes for item in TRANSFORMERS_FILES)
            completed = 0
            for item in TRANSFORMERS_FILES:
                self._check_cancel(cancel_event)
                destination = target / item.relative_path
                if destination.is_file() and destination.stat().st_size == item.size_bytes:
                    completed += item.size_bytes
                    progress(completed, total, item.relative_path)
                    continue
                url = self._transformers_url(region, item.relative_path)
                self._download_file(
                    url,
                    destination,
                    item,
                    cancel_event,
                    lambda current, name=item.relative_path, base=completed: progress(
                        base + current, total, name
                    ),
                )
                completed += item.size_bytes
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            item = ModelFile(VULKAN_FILENAME, VULKAN_SIZE, VULKAN_SHA256)
            self._download_file(
                self._vulkan_url(region),
                target,
                item,
                cancel_event,
                lambda current: progress(current, VULKAN_SIZE, VULKAN_FILENAME),
            )
        if not is_complete_model(backend, target):
            raise ModelDownloadError("下载结束，但模型文件不完整")
        return target

    @staticmethod
    def _transformers_url(region: DownloadRegion, relative_path: str) -> str:
        if region == "china":
            query = urlencode(
                {
                    "Revision": "master",
                    "FilePath": relative_path,
                }
            )
            return (
                f"https://www.modelscope.cn/api/v1/models/{TRANSFORMERS_MODEL_ID}/repo?{query}"
            )
        path = quote(relative_path, safe="/")
        return (
            f"https://huggingface.co/{TRANSFORMERS_MODEL_ID}/resolve/"
            f"{TRANSFORMERS_REVISION}/{path}"
        )

    @staticmethod
    def _vulkan_url(region: DownloadRegion) -> str:
        host = "hf-mirror.com" if region == "china" else "huggingface.co"
        return (
            f"https://{host}/{VULKAN_REPO_ID}/resolve/{VULKAN_REVISION}/"
            f"{VULKAN_FILENAME}"
        )

    def _download_file(
        self,
        url: str,
        destination: Path,
        item: ModelFile,
        cancel_event: threading.Event,
        progress: Callable[[int], None],
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_name(destination.name + ".part")
        existing = partial.stat().st_size if partial.is_file() else 0
        if existing > item.size_bytes:
            partial.unlink()
            existing = 0
        if existing == item.size_bytes:
            self._verify_and_install(partial, destination, item, cancel_event, progress)
            return
        headers = {"User-Agent": "QwenASRDesktop/1.0"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", response.getcode()))
                append = existing > 0 and status == 206
                if existing and not append:
                    existing = 0
                mode = "ab" if append else "wb"
                current = existing
                progress(current)
                with partial.open(mode) as handle:
                    while True:
                        self._check_cancel(cancel_event)
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        handle.write(block)
                        current += len(block)
                        progress(current)
                    handle.flush()
                    os.fsync(handle.fileno())
        except ModelDownloadCancelled:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            raise ModelDownloadError(f"下载 {item.relative_path} 失败：{error}") from error
        if partial.stat().st_size != item.size_bytes:
            raise ModelDownloadError(
                f"{item.relative_path} 大小不正确："
                f"{partial.stat().st_size} / {item.size_bytes} 字节"
            )
        self._verify_and_install(partial, destination, item, cancel_event, progress)
        LOGGER.info("模型文件下载并校验完成：%s", destination)

    def _verify_and_install(
        self,
        partial: Path,
        destination: Path,
        item: ModelFile,
        cancel_event: threading.Event,
        progress: Callable[[int], None],
    ) -> None:
        if item.sha256 is not None:
            progress(item.size_bytes)
            actual = self._sha256(partial, cancel_event)
            if actual != item.sha256:
                partial.unlink(missing_ok=True)
                raise ModelDownloadError(
                    f"{item.relative_path} SHA-256 校验失败，损坏文件已删除，请重试"
                )
        os.replace(partial, destination)

    @staticmethod
    def _sha256(path: Path, cancel_event: threading.Event) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while block := handle.read(4 * 1024 * 1024):
                ModelDownloadService._check_cancel(cancel_event)
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _check_cancel(cancel_event: threading.Event) -> None:
        if cancel_event.is_set():
            raise ModelDownloadCancelled("用户取消了模型下载")
