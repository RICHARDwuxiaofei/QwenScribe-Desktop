"""CLI: python -m src.gal_cutter_cli --audio ... --manifest ... --output ..."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .gal_alignment import CutterConfig
from .gal_cutter import run_cutter
from .model_service import ModelService
from .forced_aligner_service import ForcedAlignerService
from .build_config import current_build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gal TTS Alignment & Cutter (CUDA/Transformers)")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--meta", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default=None, help="cuda:N or cpu (Linux Gal CPU build defaults to cpu)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--asr-qa", action="store_true")
    parser.add_argument("--silence-threshold-db", type=float, default=-40)
    parser.add_argument("--min-silence-ms", type=int, default=80)
    parser.add_argument("--pre-roll-ms", type=int, default=70)
    parser.add_argument("--post-roll-ms", type=int, default=140)
    parser.add_argument("--tagged-event-padding-ms", type=int, default=400)
    parser.add_argument("--no-fine-silence", action="store_true")
    args = parser.parse_args(argv)
    device = args.device or ("cpu" if current_build().variant == "gal_cpu" else "cuda:0")
    if device != "cpu" and (not device.startswith("cuda:") or not device[5:].isdigit()):
        parser.error("--device must be cpu or cuda:N")
    if device == "cpu" and args.asr_qa:
        parser.error("Qwen ASR QA currently requires CUDA; omit --asr-qa for CPU cutting")
    config = CutterConfig(args.silence_threshold_db, args.min_silence_ms, args.pre_roll_ms, args.post_roll_ms, args.tagged_event_padding_ms, not args.no_fine_silence)
    asr = ModelService(device_index=int(device[5:])) if args.asr_qa else None
    try:
        aligner = ForcedAlignerService(device=device)
        try:
            result = run_cutter(args.audio, args.manifest, args.output, meta=args.meta, config=config, resume=args.resume, aligner=aligner, asr_service=asr, progress=lambda current, total, name: print(f"{current}/{total} {name}", flush=True))
        finally:
            aligner.close()
        print(f"{result['status']}: {args.output / 'alignment_report.json'}")
        return 0 if result["status"] == "COMPLETED" else 2
    except Exception as error:
        print(f"Gal Cutter 失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
