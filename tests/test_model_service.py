from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from src.model_service import ModelService


class _InferenceContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> None:
        return None


class FakeTorch:
    bfloat16 = "bf16"
    float16 = "fp16"
    cuda = SimpleNamespace(
        is_available=lambda: True,
        get_device_properties=lambda _index: SimpleNamespace(major=8),
        empty_cache=lambda: None,
        OutOfMemoryError=MemoryError,
    )

    @staticmethod
    def inference_mode() -> _InferenceContext:
        return _InferenceContext()


@dataclass
class FakeResult:
    text: str = " 测试文本 "
    language: str = "Chinese"


class FakeModel:
    def transcribe(self, *, audio: str, language: str | None) -> list[FakeResult]:
        assert Path(audio).name == "chunk.flac"
        assert language is None
        return [FakeResult()]


def test_model_service_allows_injection_without_real_model() -> None:
    captured: dict[str, object] = {}

    def factory(source: str, **kwargs: object) -> FakeModel:
        captured["source"] = source
        captured.update(kwargs)
        return FakeModel()

    service = ModelService(model_factory=factory, torch_module=FakeTorch())
    service.load()
    result = service.transcribe(Path("chunk.flac"), None)

    assert captured["max_inference_batch_size"] == 1
    assert captured["max_new_tokens"] == 2048
    assert captured["device_map"] == "cuda:0"
    assert captured["dtype"] == "bf16"
    assert result.text == "测试文本"
    assert result.language == "Chinese"
