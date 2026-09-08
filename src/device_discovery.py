"""Device enumeration outcomes shared by services, Qt signals and the GUI."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiscoveryResult:
    backend: str
    devices: tuple[tuple[str, str], ...] = ()
    ok: bool = True
    error_code: str | None = None
    error_message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        name = "Vulkan" if self.backend == "vulkan" else "CUDA"
        if not self.ok:
            return f"{name}：{self.error_message} [{self.error_code}]"
        if not self.devices:
            return f"{name}：未发现设备"
        return f"{name}：发现 {len(self.devices)} 个设备"
