"""PyInstaller runtime hook for the Vulkan/GGUF SKU."""
import os
os.environ["QWENSCRIBE_BUILD_VARIANT"] = "vulkan"
