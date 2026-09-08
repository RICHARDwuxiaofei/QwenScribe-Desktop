"""PyInstaller runtime hook for the opt-in dual-backend diagnostic SKU."""
import os
os.environ["QWENSCRIBE_BUILD_VARIANT"] = "full"
