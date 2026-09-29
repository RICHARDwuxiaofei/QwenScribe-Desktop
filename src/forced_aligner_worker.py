"""Persistent, isolated CUDA Forced Aligner JSON-line process."""
from __future__ import annotations

import contextlib
import gc
import json
import sys
import traceback


def reply(stream, ok: bool, **payload):
    stream.write(json.dumps({"ok": ok, **payload}, ensure_ascii=False) + "\n")
    stream.flush()


def main() -> int:
    protocol = sys.stdout
    model = None
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        from qwen_asr import Qwen3ForcedAligner
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            command = request.get("command")
            if command == "close":
                reply(protocol, True, result={})
                return 0
            if command == "load":
                device_name = str(request.get("device", f"cuda:{request.get('device_index', 0)}"))
                if device_name == "cpu":
                    dtype = torch.float32
                elif device_name.startswith("cuda:") and device_name[5:].isdigit():
                    device = int(device_name[5:])
                    if not torch.cuda.is_available() or not 0 <= device < torch.cuda.device_count():
                        raise RuntimeError(f"CUDA {device_name} 不可用")
                    dtype = torch.bfloat16 if torch.cuda.get_device_properties(device).major >= 8 else torch.float16
                else:
                    raise RuntimeError(f"不支持的 Forced Aligner 设备：{device_name}")
                with contextlib.redirect_stdout(sys.stderr):
                    model = Qwen3ForcedAligner.from_pretrained(request["model_source"], dtype=dtype, device_map=device_name)
                reply(protocol, True, result={"device": device_name})
            elif command == "align":
                if model is None:
                    raise RuntimeError("Forced Aligner 尚未加载")
                with torch.inference_mode(), contextlib.redirect_stdout(sys.stderr):
                    results = model.align(audio=request["audio"], text=request["text"], language=request["language"])
                if len(results) != 1:
                    raise RuntimeError("Forced Aligner 返回了非单 batch 结果")
                reply(protocol, True, result={"units": [{"text": u.text, "start_time": u.start_time, "end_time": u.end_time} for u in results[0]]})
            elif command == "clear_cache":
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                reply(protocol, True, result={})
            else:
                raise RuntimeError(f"未知命令：{command}")
        except torch.cuda.OutOfMemoryError as error:
            reply(protocol, False, error_type="cuda_oom", message=str(error))
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            reply(protocol, False, error_type="error", message=str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
