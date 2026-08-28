# Third-party notices

## PuriPulyHeartGpuWorker

The optional Vulkan/GGUF backend uses `PuriPulyHeartGpuWorker.exe`, built from:

- Source: https://github.com/RICHARDwuxiaofei/PuriPuly-heart
- Pinned build commit: `6f83741c7e68d9d13b2efa306d3427df447d576b`
- Component: `native/gpu_worker`
- License declared by that component: AGPL-3.0-or-later
- Backend dependency: `transcribe-cpp` with its Vulkan feature

The worker remains a separate local process and communicates with QwenASRDesktop over an authenticated loopback-only JSON-lines protocol. GitHub Actions copies the upstream `LICENSE` into the release as `LICENSE-PuriPulyHeartGpuWorker-AGPL-3.0.txt`; the pinned corresponding source remains available at the repository and commit above.

## Qwen3-ASR-1.7B Q6_K GGUF

- Model repository: https://huggingface.co/handy-computer/Qwen3-ASR-1.7B-gguf
- Upstream model: Qwen/Qwen3-ASR-1.7B
- Local filename: `models/Qwen3-ASR-1.7B-Q6_K.gguf`

Model weights are external data and are intentionally not embedded into a PyInstaller executable. Review the model repositories' licenses before redistribution.

The application offers ModelScope for the official Transformers checkpoint in Mainland China and Hugging Face internationally. For the Q6_K file, the Mainland-China route uses the community service `hf-mirror.com`; the downloaded file must match SHA-256 `c75a961b7134a6c952d89797865cb0d0376876185aee04ef6d12c31c2952e4e1` before it is installed.
