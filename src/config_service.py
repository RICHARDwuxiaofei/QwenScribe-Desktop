"""JSON-backed per-user application settings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from platformdirs import user_config_path


LOGGER = logging.getLogger(__name__)


class ConfigService:
    """Load and atomically save a small JSON settings document."""

    def __init__(self, config_path: Path | None = None) -> None:
        base = user_config_path("QwenASRDesktop", appauthor=False)
        self.path = config_path or (base / "config.json")
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            self.data = {}
            return self.data
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            self.data = loaded if isinstance(loaded, dict) else {}
        except (OSError, json.JSONDecodeError):
            LOGGER.exception("无法读取配置文件 %s", self.path)
            self.data = {}
        return self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def update(self, values: dict[str, Any]) -> None:
        self.data.update(values)
        self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)
        except OSError:
            LOGGER.exception("无法保存配置文件 %s", self.path)
