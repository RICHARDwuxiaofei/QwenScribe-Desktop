from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest

from src.model_catalog import ModelFile
from src.model_download_service import ModelDownloadService


class _Response:
    status = 206

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        block = self._data[self._offset : self._offset + size]
        self._offset += len(block)
        return block


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
