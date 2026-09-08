from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from src.model_catalog import ModelFile
from src.model_download_service import (
    ModelDownloadCancelled,
    ModelDownloadService,
)


class _Response:
    status = 206

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
        return None

    def close(self) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        block = self._data[self._offset : self._offset + size]
        self._offset += len(block)
        return block

    def read1(self, size: int) -> bytes:
        return self.read(size)


def test_download_file_resumes_and_verifies_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete-model-payload"
    destination = tmp_path / "model.bin"
    partial = destination.with_name("model.bin.part")
    partial.write_bytes(payload[:8])

    def fake_urlopen(_request: object, timeout: float) -> _Response:
        assert timeout == 60.0
        return _Response(payload[8:])

    monkeypatch.setattr("src.model_download_service.urlopen", fake_urlopen)
    item = ModelFile(
        "model.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )
    ModelDownloadService()._download_file(
        "https://example.invalid/model.bin",
        destination,
        item,
        threading.Event(),
        lambda _current: None,
    )
    assert destination.read_bytes() == payload
    assert not partial.exists()


def test_cancel_preserves_partial_and_does_not_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete-model-payload"
    destination = tmp_path / "model.bin"
    partial = destination.with_name("model.bin.part")
    cancel_event = threading.Event()

    monkeypatch.setattr(
        "src.model_download_service.urlopen",
        lambda _request, timeout: _Response(payload),
    )
    item = ModelFile("model.bin", len(payload), hashlib.sha256(payload).hexdigest())

    with pytest.raises(ModelDownloadCancelled):
        ModelDownloadService()._download_file(
            "https://example.invalid/model.bin",
            destination,
            item,
            cancel_event,
            lambda current: cancel_event.set() if current else None,
        )

    assert not destination.exists()
    assert partial.read_bytes() == payload


def test_cancel_before_install_keeps_complete_partial(tmp_path: Path) -> None:
    payload = b"complete-model-payload"
    destination = tmp_path / "model.bin"
    partial = destination.with_name("model.bin.part")
    partial.write_bytes(payload)
    cancel_event = threading.Event()
    cancel_event.set()
    item = ModelFile("model.bin", len(payload), hashlib.sha256(payload).hexdigest())

    with pytest.raises(ModelDownloadCancelled):
        ModelDownloadService()._download_file(
            "https://example.invalid/model.bin",
            destination,
            item,
            cancel_event,
            lambda _current: None,
        )

    assert not destination.exists()
    assert partial.read_bytes() == payload


def test_cancel_after_hash_keeps_partial_before_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete-model-payload"
    destination = tmp_path / "model.bin"
    partial = destination.with_name("model.bin.part")
    partial.write_bytes(payload)
    cancel_event = threading.Event()
    item = ModelFile("model.bin", len(payload), hashlib.sha256(payload).hexdigest())
    service = ModelDownloadService()

    def hash_then_cancel(_path: Path, _event: threading.Event) -> str:
        cancel_event.set()
        return item.sha256 or ""

    monkeypatch.setattr(service, "_sha256", hash_then_cancel)
    with pytest.raises(ModelDownloadCancelled):
        service._download_file(
            "https://example.invalid/model.bin",
            destination,
            item,
            cancel_event,
            lambda _current: None,
        )

    assert not destination.exists()
    assert partial.read_bytes() == payload


def test_cancelled_read_is_not_reported_as_download_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "model.bin"
    cancel_event = threading.Event()

    class _StalledResponse(_Response):
        def read(self, _size: int) -> bytes:
            cancel_event.set()
            raise OSError("response closed")

    monkeypatch.setattr(
        "src.model_download_service.urlopen",
        lambda _request, timeout: _StalledResponse(b""),
    )
    item = ModelFile("model.bin", 3, None)

    with pytest.raises(ModelDownloadCancelled):
        ModelDownloadService()._download_file(
            "https://example.invalid/model.bin",
            destination,
            item,
            cancel_event,
            lambda _current: None,
        )


def test_resume_after_cancel_uses_range_and_installs_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"complete-model-payload"
    destination = tmp_path / "model.bin"
    partial = destination.with_name("model.bin.part")
    cancel_event = threading.Event()
    requests: list[object] = []

    monkeypatch.setattr(
        "src.model_download_service.urlopen",
        lambda request, timeout: (requests.append(request) or _Response(payload[:8])),
    )
    item = ModelFile("model.bin", len(payload), hashlib.sha256(payload).hexdigest())
    service = ModelDownloadService()
    with pytest.raises(ModelDownloadCancelled):
        service._download_file(
            "https://example.invalid/model.bin",
            destination,
            item,
            cancel_event,
            lambda current: cancel_event.set() if current else None,
        )
    first_partial_size = partial.stat().st_size
    assert first_partial_size > 0

    cancel_event.clear()
    remaining = payload[first_partial_size:]

    class _ResumeResponse(_Response):
        status = 206

    monkeypatch.setattr(
        "src.model_download_service.urlopen",
        lambda request, timeout: (
            requests.append(request) or _ResumeResponse(remaining)
        ),
    )
    service._download_file(
        "https://example.invalid/model.bin",
        destination,
        item,
        cancel_event,
        lambda _current: None,
    )

    assert requests[1].get_header("Range") == f"bytes={first_partial_size}-"
    assert destination.read_bytes() == payload
    assert not partial.exists()


def test_abort_active_io_closes_response() -> None:
    class _Closable:
        closed = False

        def close(self) -> None:
            self.closed = True

    response = _Closable()
    service = ModelDownloadService()
    service._set_active_response(response)
    service.abort_active_io()
    assert response.closed


def test_transformers_cancel_keeps_completed_files_and_resumes_current_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = ModelFile("first.bin", 5, None)
    payload = b"second-model"
    second = ModelFile("second.bin", len(payload), hashlib.sha256(payload).hexdigest())
    target = tmp_path / "transformers"
    target.mkdir()
    (target / first.relative_path).write_bytes(b"first")
    monkeypatch.setattr("src.model_download_service.TRANSFORMERS_FILES", (first, second))
    monkeypatch.setattr("src.model_download_service.download_target", lambda _backend: target)
    monkeypatch.setattr("src.model_download_service.is_complete_model", lambda *_args: True)

    cancel_event = threading.Event()
    requests: list[object] = []
    monkeypatch.setattr(
        "src.model_download_service.urlopen",
        lambda request, timeout: (requests.append(request) or _Response(payload[:6])),
    )
    service = ModelDownloadService()

    def cancel_current_file(current: int, _total: int, name: str) -> None:
        if name == "second.bin" and current > first.size_bytes:
            cancel_event.set()

    with pytest.raises(ModelDownloadCancelled):
        service.download("transformers", "international", cancel_event, cancel_current_file)
    current_partial = target / "second.bin.part"
    assert (target / "first.bin").read_bytes() == b"first"
    assert current_partial.read_bytes() == payload[:6]

    cancel_event.clear()
    remaining = payload[6:]

    class _ResumeResponse(_Response):
        status = 206

    monkeypatch.setattr(
        "src.model_download_service.urlopen",
        lambda request, timeout: (
            requests.append(request) or _ResumeResponse(remaining)
        ),
    )
    service.download("transformers", "international", cancel_event, lambda *_args: None)
    assert requests[1].get_header("Range") == "bytes=6-"
    assert (target / "second.bin").read_bytes() == payload
    assert not current_partial.exists()
