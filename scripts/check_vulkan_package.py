"""Reject system Vulkan components accidentally collected from a build host."""

import json
from pathlib import Path
import sys


def forbidden_vulkan_files(root: Path) -> list[Path]:
    forbidden = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name == "vulkan-1.dll" or name.startswith("vklayer_") or name.startswith("vk_layer_"):
            forbidden.append(path)
        elif path.suffix.lower() == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (ValueError, OSError, UnicodeError):
                continue
            if isinstance(data, dict) and "file_format_version" in data and any(
                key in data for key in ("ICD", "layer", "layers")
            ):
                forbidden.append(path)
    return forbidden


if __name__ == "__main__":
    root = Path(sys.argv[1])
    if not root.is_dir():
        raise SystemExit(f"Package directory missing: {root}")
    forbidden = forbidden_vulkan_files(root)
    if forbidden:
        raise SystemExit("System Vulkan components must not be bundled: " + ", ".join(map(str, forbidden)))
    print("Package contains no Vulkan loader, layers or ICD manifests")
