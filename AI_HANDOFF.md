# QwenScribe Desktop — AI Handoff

## 1. 当前状态

更新时间：2026-09-07

这是一个 Windows 11 x64、本地运行的 PySide6 音视频转文字应用。模型保存在用户数据目录，媒体处理使用随包 FFmpeg/FFprobe，识别后端通过独立子进程或 worker 与 GUI 隔离。

当前工作分支和提交：

- branch：`codex/reduce-windows-package-size`
- HEAD：`c73a5cf9731378c4a66f8bbcf3dc546ca5112652`
- `origin/main` 仍为原主线；本分支尚未合并。
- 当前工作树应保持干净。不要 reset、rebase、force push、覆盖用户修改或合并到 main。

发布体积拆分已经实现并通过 CI：

- `QwenScribe-Vulkan-Windows-x64`：Vulkan/GGUF 默认 SKU。
- `QwenScribe-CUDA-Windows-x64`：CUDA/Transformers 可选 SKU。
- `full`：仅供显式诊断构建，不能作为普通 push 或正式发布附件。

最近修复的 CI 问题是 size report 将 PyAV 的 `_internal\av\audio\*.pyd` 和 `_internal\av\video\*.pyd` 判成 forbidden。现已改为只匹配真实禁止文件扩展名和明确缓存目录；`safetensors` Python 包目录合法，真实 `*.safetensors` 权重文件仍会失败。

## 2. 最新 CI 与 Artifact

GitHub Actions run：

- Run `33258632537`：成功。
- `Vulkan GGUF SKU`：成功，job `99116617318`。
- `CUDA Transformers SKU`：成功，job `99116617357`。

Artifacts：

- Vulkan Artifact ID `9716716709`，GitHub 外层 Artifact 约 `106,903,233` bytes。
- CUDA Artifact ID `9716843693`，GitHub 外层 Artifact `2,241,362,473` bytes。
- CUDA 内部 7z 分卷合计 `2,240,868,724` bytes（2138 MiB，2 volumes）。
- CUDA 包解压大小为 `5,094,437,339` bytes（约 4.86 GiB）。
- Vulkan 本机验证目录：解压约 `653.81 MiB`，ZIP 约 `253.97 MiB`；FFmpeg/FFprobe 约 `423.71 MiB`，Vulkan worker 约 `74.17 MiB`。

CI 已验证：34 项测试、PyInstaller 构建、打包后 `--check`、FFmpeg/FFprobe、短 WAV、`silencedetect`、后端边界检查、归档、manifest 和 Artifact 上传。GitHub runner 没有真实 GPU，因此以下仍必须人工验收：实际 GPU 枚举、模型下载/加载、真实音频 STT、断网复用。

## 3. 产品与后端边界

### Vulkan SKU

包含 PySide6/Python runtime、FFmpeg/FFprobe、固定 Vulkan worker 和 Vulkan/GGUF 客户端；不包含：

- `torch` / `torchgen`
- `transformers` / `qwen_asr` / `accelerate`
- CUDA、cuDNN、cuBLAS 等运行时
- 模型权重

适合 Intel/AMD/NVIDIA 的 Vulkan 设备。Ryzen 7 6800HS 笔记本通常带 Radeon 680M 核显，应该使用该 SKU；最终是否可用取决于 Windows AMD 驱动和 worker 的实际 Vulkan 枚举结果。

### CUDA SKU

包含 qwen-asr/Transformers/PyTorch CUDA 路线和独立 Transformers 子进程；不包含 Vulkan worker，也不包含模型。仅适合带 NVIDIA CUDA GPU 的机器。下载两个 7z 分卷后，从 `.001` 文件开始解压。

### 必须保持的设计

- Transformers 模型在独立子进程中加载和推理。
- Vulkan 通过独立 worker 进程运行。
- 显式 GPU device ID 与实际设备 ID 不一致必须失败，禁止静默切换或回退。
- batch size 固定为 1。
- 后端或 GPU 切换后要求重启。
- partial 文本文件的崩溃恢复和成功后原子改名不能删除。
- 模型完全外置；不得提交或打包 `.gguf`/`.safetensors`。
- FFmpeg/FFprobe 使用参数列表、无 shell 拼接、Windows 无黑框子进程。
- 不改写当前 TXT 文本格式和分段核心语义。

## 4. 运行架构

```text
PySide6 MainWindow
  -> TranscriptionWorker (QThread)
     -> MediaService -> FFprobe/FFmpeg child processes
     -> Segmenter -> pure boundary calculation
     -> Transformers ModelService -> persistent Python subprocess -> CUDA
     -> VulkanModelService -> authenticated loopback worker -> Vulkan

ModelDownloadService -> ModelScope/Hugging Face/hf-mirror
Config/Logging -> platformdirs user data
Output -> UTF-8 TXT plus crash-safe partial TXT
```

正常转写不联网；只有模型缺失且用户选择下载线路时访问模型站点。模型下载支持 `.part`、断点续传、固定 revision、大小检查和权重 SHA-256 校验。

## 5. 关键文件

- `app.py`：GUI/worker 入口；`--check` 和打包后诊断入口。
- `src/build_config.py`：唯一 build variant/capability 声明点。
- `src/main_window.py`：UI、拖放、队列、设置和后端可用性提示。
- `src/transcription_worker.py`：任务编排、进度、取消、partial、OOM 细分。
- `src/media_service.py`、`src/segmenter.py`：媒体处理和分段。
- `src/model_service.py`、`src/transformers_worker.py`：CUDA/Transformers 独立进程。
- `src/vulkan_model_service.py`：Vulkan worker 协议和严格设备选择。
- `src/model_catalog.py`、`src/model_download_service.py`：模型路径、revision、下载和校验。
- `QwenASRDesktop.spec`：参数化 PyInstaller onedir；读取 `QWENSCRIBE_BUILD_VARIANT`。
- `.github/workflows/windows-build.yml`：Vulkan/CUDA 两个独立 Windows job。
- `scripts/report_package_size.ps1`：体积清单、分类、manifest 支撑和 forbidden 检查。
- `tests/test_package_size_report.py`：目录名合法、模型扩展名非法的回归测试。
- `requirements-common.txt`、`requirements-vulkan.txt`、`requirements-cuda.txt`、`requirements-dev.txt`：SKU 依赖拆分。
- `README.md`、`使用说明.md`、`发布与云编译.md`、`THIRD_PARTY_NOTICES.md`：用户和发布文档。

## 6. 本地开发与测试

在仓库根目录：

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp
```

当前本地完整测试结果：`36 passed`。

基础诊断：

```powershell
.\.venv\Scripts\python.exe app.py --check
```

报告脚本示例：

```powershell
.\scripts\report_package_size.ps1 `
  -PackageDirectory <解压后的 SKU 目录> `
  -BuildVariant vulkan `
  -OutputDirectory <报告目录>
```

该脚本输出 `packaging-size-report.json` 和 `.md`，区分 Git 跟踪大小、解压包大小、压缩 Artifact、FFmpeg、外置模型和首次可用下载量。

本地构建变体：

```powershell
$env:QWENSCRIBE_BUILD_VARIANT = 'vulkan'  # 或 cuda/full
python -m PyInstaller --clean --noconfirm QwenASRDesktop.spec
```

不要把本地 `.venv`、模型、下载缓存、日志、媒体或 `.part` 文件加入 Git。

## 7. 用户配置与路径

用户配置：`%LOCALAPPDATA%\QwenASRDesktop\config.json`

日志：`%LOCALAPPDATA%\QwenASRDesktop\Logs\QwenASRDesktop.log`

重要环境变量：

- `QWEN_ASR_MODEL_PATH`：官方 Transformers 模型目录。
- `QWEN_ASR_VULKAN_MODEL_PATH`：Q6_K GGUF 路径。
- `QWENSCRIBE_BUILD_VARIANT`：构建时使用；打包 runtime hook 会固定变体。
- `QWENSCRIBE_RUN_CHECK` / `QWENSCRIBE_CHECK_OUTPUT`：CI 使用的无 GUI 诊断路径。

如果用户配置保存了当前 SKU 不支持的 backend，程序必须提示“当前发行版本不包含该后端”，引导用户切换到支持的后端或下载另一 SKU；不得静默改 GPU 或覆盖配置。

## 8. 当前已知限制与未完成验收

这些不是当前 CI 的代码失败，但在正式发布前不能省略：

- 尚未在一台全新的、无开发 Python、无源码、无 `.venv`、无本机 PATH 补充的 Windows 11 电脑上完成完整验收。
- 尚未在 Radeon 680M 或其他目标 Vulkan GPU 上完成真实模型加载和真实音频 STT。
- 尚未在真实 NVIDIA 机器上重新验证最新 CUDA Artifact 的模型加载、显式 device ID 和 STT。
- 尚未完成已下载模型断网复用的实机验收。
- 无签名安装程序；Artifact 是可解压的 onedir 发行包。
- CUDA 运行中的取消只能等待当前片段结束，不强杀 CUDA kernel。
- 管理员权限进程无法接收普通权限资源管理器的拖放，这是 Windows 权限隔离行为。

因此目前可以把 Artifact 交给用户做实机验收，但不要在没有这些证据时声称“正式 Release 已完成”。

## 9. 下一位 AI 的工作顺序

1. 先运行 `git status --short`、`git branch --show-current`、`git rev-parse HEAD`、`git log -10 --oneline --decorate`。
2. 阅读本文件、`README.md`、`发布与云编译.md`、`THIRD_PARTY_NOTICES.md`；只按任务定向阅读源码。
3. 修改前确认没有用户未提交修改，不要 reset/rebase/checkout 覆盖工作树。
4. 任何后端改动都必须保留进程隔离、严格设备 ID、partial 恢复和模型外置。
5. 体积改动先生成 size report，禁止凭 DLL 文件名盲删 CUDA 运行时。
6. 改动后至少运行 36 项 pytest、compileall、相关报告脚本和 `git diff --check`。
7. Windows 构建使用独立 Vulkan/CUDA job；普通 push 不生成 full SKU，不创建 tag/Release。
8. 只有完成 Artifact 下载、SHA-256、全新目录启动、真实 GPU/FFmpeg/模型/STT 和断网验收后，才可讨论正式发布。

## 10. Git / 发布禁令

本项目当前没有创建 `v1.0.0` tag，也没有创建 GitHub Release。除非用户明确授权，否则不得：

- 合并到 `main`；
- 创建或推送 tag；
- 创建 GitHub Release；
- force push、reset、rebase 或重写历史；
- 提交模型、`.venv`、下载缓存、日志、媒体、`.part` 或凭据；
- 修改只读参考项目 PuriPuly-heart。

PuriPuly-heart 仅用于 Vulkan worker/协议参考；本仓库 workflow 使用固定 commit 构建 worker，不要向上游推送修改。
