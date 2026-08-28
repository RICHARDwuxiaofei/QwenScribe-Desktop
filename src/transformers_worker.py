"""Line-oriented worker that isolates native PyTorch/CUDA failures from Qt."""

from __future__ import annotations

import contextlib
import gc
import json
import sys
import traceback
from typing import Any, TextIO


def _reply(stream: TextIO, *, ok: bool, **payload: Any) -> None:
    stream.write(json.dumps({"ok": ok, **payload}, ensure_ascii=False) + "\n")
    stream.flush()


def main() -> int:
    protocol = sys.stdout
    model: Any | None = None
    torch: Any | None = None
    with contextlib.redirect_stdout(sys.stderr):
        import torch as torch_module
        from qwen_asr import Qwen3ASRModel

        torch = torch_module

    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
            command = str(request.get("command", ""))
            if command == "close":
                _reply(protocol, ok=True, result={})
                return 0
            if command == "load":
                device_index = int(request["device_index"])
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA 不可用")
                if device_index < 0 or device_index >= torch.cuda.device_count():
                    raise RuntimeError(f"CUDA 设备 cuda:{device_index} 当前不可用")
                properties = torch.cuda.get_device_properties(device_index)
                dtype = torch.bfloat16 if int(properties.major) >= 8 else torch.float16
                with contextlib.redirect_stdout(sys.stderr):
                    model = Qwen3ASRModel.from_pretrained(
                        str(request["model_source"]),
                        dtype=dtype,
                        device_map=f"cuda:{device_index}",
                        max_inference_batch_size=1,
                        max_new_tokens=2048,
                    )
                _reply(
                    protocol,
                    ok=True,
                    result={"device": f"cuda:{device_index}", "dtype": str(dtype)},
                )
                continue
            if command == "transcribe":
                if model is None:
                    raise RuntimeError("模型尚未加载")
                with torch.inference_mode(), contextlib.redirect_stdout(sys.stderr):
                    results = model.transcribe(
                        audio=str(request["audio"]), language=request.get("language")
                    )
                if not results:
                    raise RuntimeError("模型没有返回识别结果")
                first = results[0]
                _reply(
                    protocol,
                    ok=True,
                    result={
                        "text": str(getattr(first, "text", "")).strip(),
                        "language": getattr(first, "language", None),
                    },
                )
                continue
            if command == "clear_cache":
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                _reply(protocol, ok=True, result={})
                continue
            raise RuntimeError(f"未知模型命令：{command}")
        except torch.cuda.OutOfMemoryError as error:
            _reply(protocol, ok=False, error_type="cuda_oom", message=str(error))
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            _reply(protocol, ok=False, error_type="error", message=str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
