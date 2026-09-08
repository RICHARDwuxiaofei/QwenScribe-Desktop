from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCRIPT = REPO_ROOT / "scripts" / "report_package_size.ps1"


def run_report(package: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-File",
            str(REPORT_SCRIPT),
            "-PackageDirectory",
            str(package),
            "-BuildVariant",
            "cuda",
            "-OutputDirectory",
            str(output),
            "-ModelBytes",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_cuda_python_safetensors_package_is_not_forbidden(tmp_path: Path) -> None:
    package = tmp_path / "QwenScribe-CUDA-Windows-x64"
    (package / "_internal" / "safetensors").mkdir(parents=True)
    (package / "_internal" / "safetensors" / "__init__.py").write_text("", encoding="utf-8")
    (package / "_internal" / "av" / "audio").mkdir(parents=True)
    (package / "_internal" / "av" / "audio" / "frame.py").write_text("", encoding="utf-8")
    (package / "_internal" / "modelscope" / "msdatasets" / "download").mkdir(parents=True)
    (package / "_internal" / "modelscope" / "msdatasets" / "download" / "download_manager.py").write_text("", encoding="utf-8")

    result = run_report(package, tmp_path / "report")

    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "report" / "packaging-size-report.json").read_text(encoding="utf-8-sig"))
    assert report["forbidden_content"] == []


def test_actual_safetensors_model_file_is_forbidden(tmp_path: Path) -> None:
    package = tmp_path / "QwenScribe-CUDA-Windows-x64"
    package.mkdir()
    (package / "model.safetensors").write_bytes(b"not a model")

    result = run_report(package, tmp_path / "report")

    assert result.returncode != 0
    report = json.loads((tmp_path / "report" / "packaging-size-report.json").read_text(encoding="utf-8-sig"))
    assert [entry["path"] for entry in report["forbidden_content"]] == ["model.safetensors"]
