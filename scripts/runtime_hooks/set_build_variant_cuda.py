"""PyInstaller runtime hook for the CUDA/Transformers SKU."""
import os
os.environ["QWENSCRIBE_BUILD_VARIANT"] = "cuda"
