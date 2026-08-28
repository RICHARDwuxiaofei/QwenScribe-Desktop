"""Manual Vulkan backend smoke test without printing transcript text."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.transcription_worker import TranscriptionTask, TranscriptionWorker
from src.vulkan_model_service import VulkanModelService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--device-id", default="vulkan-index-1")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    service = VulkanModelService(PROJECT_ROOT, device_id=args.device_id)
    worker = TranscriptionWorker(PROJECT_ROOT, model_service=service)
    completed: list[Path] = []
    failures: list[str] = []
    worker.task_completed.connect(lambda value: completed.append(Path(value)))
    worker.task_failed.connect(lambda summary, _partial: failures.append(summary))
    try:
        worker.start_task(
            TranscriptionTask(
                input_path=args.audio.resolve(),
                output_directory=args.output_dir.resolve(),
                language=None,
            )
        )
    finally:
        service.close()
    if failures:
        raise RuntimeError(failures[-1])
    if len(completed) != 1 or not completed[0].is_file():
        raise RuntimeError("Vulkan smoke test did not create exactly one final TXT")
    text = completed[0].read_text(encoding="utf-8")
    print(
        f"Vulkan smoke passed: device={args.device_id} "
        f"output={completed[0]} chars={len(text)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
