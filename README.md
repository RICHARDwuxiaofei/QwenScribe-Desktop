# QwenScribe Desktop

[中文](#中文简介) · [English](#english-overview)

## 中文简介

QwenScribe Desktop（内部项目名 QwenASRDesktop）是面向 Windows 11 的完全本地视频/音频转文字桌面应用。它支持两套可切换后端：官方 `qwen-asr` Transformers + PyTorch CUDA，以及 Qwen3-ASR-1.7B Q6_K GGUF + transcribe.cpp Vulkan。Vulkan 后端可以严格选择 Intel 核显或 NVIDIA 独显。输入文件不会上传，最终只生成 UTF-8 TXT。界面可在简体中文和 English 之间即时切换。

## English Overview

QwenScribe Desktop is a fully local video and audio transcription app for Windows 11. It supports two selectable inference backends: the official `qwen-asr` Transformers backend with PyTorch CUDA, and a Qwen3-ASR-1.7B Q6_K GGUF backend powered by transcribe.cpp/Vulkan. The Vulkan route can target an explicitly selected integrated or discrete GPU. Media never leaves the computer, and the only final output is a clean UTF-8 TXT file without timestamps.

Highlights:

- Drag and drop one or more videos/audio files, or recursively add a folder.
- Dynamically detects available CUDA and Vulkan devices; it never hard-codes or silently changes the selected GPU.
- Splits long recordings around silence and processes one segment at a time, so multi-hour media is not loaded into GPU memory at once.
- Writes every completed segment to a crash-resistant `.partial.txt` before producing the final TXT.
- Keeps the Transformers/CUDA model in an isolated persistent process so a native GPU runtime crash cannot directly terminate the GUI.
- Downloads models only when needed, with separate mainland-China and international routes; downloaded models can be used offline.
- Runtime interface switching between Simplified Chinese and English. The interface language is independent from the audio recognition language.

Quick start on Windows 11 with 64-bit Python 3.12:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1
.\run.bat
```

Requirements: a CUDA-capable NVIDIA GPU for the official Transformers backend, or a supported Vulkan GPU and the packaged worker for the GGUF backend; FFmpeg and FFprobe are also required. Release packages include FFmpeg/FFprobe and the Vulkan worker, but never include model weights. On first transcription, choose the China or international download route in the app. See the Chinese sections below for detailed installation, model paths, troubleshooting, testing, and release instructions.

## 中文详细文档

## 功能与边界

- 深色队列式界面，支持拖放、一次选择多个文件、递归添加文件夹、逐文件状态和结果预览。
- i18n 界面支持简体中文 / English 即时切换，并自动记住选择；界面语言不改变音频识别语言。
- 支持 `mp4/mkv/mov/avi/webm/m4v/mp3/wav/flac/m4a/aac/ogg`；队列在单张 GPU 上顺序处理，不并发加载多个长片段。
- FFprobe 验证音轨和时长；FFmpeg 提取第一条音轨为临时的 16 kHz 单声道 PCM WAV。逐段送入模型前再生成小型 FLAC，避免部分长 AAC 转码后出现 FLAC 随机切片错误。
- 依据静音点规划约 180 秒的分段，每次只创建并识别一个片段。两小时媒体不会整体载入内存或显存。
- Transformers 模型以 `max_inference_batch_size=1` 加载一次；Vulkan GGUF worker 也保持常驻。两套模型不会同时加载。
- 自动语言识别传 `language=None`；手动语言使用 Qwen3-ASR 的标准英文名称。
- 不加载 Forced Aligner、不请求时间戳、不生成 SRT/VTT、不调用云端 ASR API。
- 每个非空片段完成后立即写入并同步 `*.partial.txt`；成功后安全改名为最终 TXT。
- CUDA/Vulkan OOM 时清理可用缓存并递归二分当前片段，最小约 30 秒、最多四层。
- 取消会终止正在运行的 FFmpeg；CUDA 推理会在当前调用返回后停止。

## 系统要求

- Windows 11 64 位
- Python 3.12 64 位
- NVIDIA 显卡和较新的 NVIDIA 驱动（目标配置为 RTX 4070 Super 12GB）
- CUDA 版 PyTorch
- FFmpeg 与 FFprobe
- 首次下载模型时需要网络和足够磁盘空间
- 发布包内含 FFmpeg、FFprobe 和 Vulkan worker，但不含任何模型权重

FlashAttention 2 不是依赖。项目默认使用 PyTorch / `qwen-asr` 自带的 attention 实现，以降低 Windows 安装难度。

## 推荐安装方式

1. 安装 [Python 3.12 for Windows](https://www.python.org/downloads/windows/)，并保留 Python Launcher。
2. 安装/更新 NVIDIA 驱动。
3. 在项目目录打开 PowerShell，然后运行：

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\install_windows.ps1
   ```

安装脚本会检查 Python 3.12、创建 `.venv`、安装 CUDA 版 PyTorch、安装其余依赖、检查 FFmpeg，并打印 CUDA/GPU 信息。

脚本默认使用 PyTorch `cu128` wheel 索引。PyTorch 提供的 Windows CUDA wheel 会随版本更新；如 [PyTorch 官方安装页](https://pytorch.org/get-started/locally/) 当前建议了不同索引，请显式传入：

```powershell
.\install_windows.ps1 -TorchIndexUrl "https://download.pytorch.org/whl/cuXXX"
```

`requirements.txt` 故意不固定 `torch`，避免普通 PyPI 解析意外替换为不合适的版本。应始终先安装官方 CUDA wheel，再安装应用依赖。

## 安装 FFmpeg

应用按以下顺序查找：

1. 项目目录的 `bin\ffmpeg.exe` 和 `bin\ffprobe.exe`；
2. 系统 `PATH`。

可从 [FFmpeg 官方下载页](https://ffmpeg.org/download.html#build-windows) 选择 Windows build。解压后可以把 `ffmpeg.exe` 与 `ffprobe.exe` 复制到本项目的 `bin` 目录，也可以把发行版的 `bin` 目录加入系统 `PATH`。用下面命令检查：

```powershell
ffmpeg -version
ffprobe -version
```

请勿只安装其中一个文件。

## 启动

双击：

```text
run.bat
```

或在已激活的虚拟环境中运行：

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

首次点击“开始转写”且所选模型不存在时，程序会先询问下载线路：

- **中国境内（推荐）**：Transformers 使用 Qwen 官方推荐的 ModelScope；Vulkan Q6_K 使用 `hf-mirror.com` 社区镜像，并在完成后校验固定大小和 SHA-256。
- **国际 / Hugging Face**：从固定版本的 Hugging Face 仓库下载。

下载在后台线程执行，不会卡住主窗口；支持 `.part` 断点续传和取消。模型保存在当前用户的数据目录，通常是：

```text
C:\Users\你的用户名\AppData\Local\QwenASRDesktop\models
```

两套模型都不会打入发布 ZIP，也不会上传到 GitHub。模型下载完成后可断网转写。VPN 并不必然更快；人在中国境内时，通常先选国内线路，失败后再换国际线路。

中国大陆推荐使用 Qwen 官方文档给出的 ModelScope 下载方式：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\download_model_cn.ps1
```

该脚本是源码开发环境的备用方式。发布版用户无需运行脚本，直接使用应用内下载窗口即可。

界面使用方法：把一个或多个媒体文件拖进窗口，也可以选择文件或文件夹；设置统一的输出目录与语言后点击“开始转写队列”。模型第一次加载后会驻留并由后续文件复用。列表中可查看每个文件的状态、进度和完整路径，选择已完成或保留 partial 的项目可预览文本。

## 推理方式、模型与 GPU 切换

界面提供三个相关选择：

- **推理方式**：`官方 Transformers（PyTorch CUDA）` 或 `transcribe.cpp（Vulkan GGUF）`。
- **模型**：官方 1.7B BF16/FP16 或 1.7B Q6_K GGUF。模型格式与推理方式绑定，选择模型会同步选择兼容后端。
- **GPU**：Transformers 只列出 PyTorch CUDA 设备；Vulkan 会列出 worker 实际发现的全部设备，包括 Intel UHD Graphics 770 核显和 RTX 4070 SUPER 独显。

设备列表不是固定写死的。窗口显示后，后台会枚举当前电脑的全部 CUDA 和 Vulkan 设备，并显示实际设备 ID、名称、类型和显存/共享内存。换到另一台电脑会得到那台电脑自己的列表。检测期间下拉框显示“正在检测”，不会阻塞窗口。

修改推理方式或 GPU 后需要关闭程序并重新运行 `run.bat`。这样可以先释放旧模型，再加载另一套模型，避免两套 1.7B 同时占用内存。程序保存明确的设备 ID；如果所选设备不可用会直接报错，不会静默换用另一张 GPU、CPU 或另一后端。

源码开发目录当前可使用：

```text
bin\PuriPulyHeartGpuWorker.exe
models\Qwen3-ASR-1.7B-Q6_K.gguf
```

也可以分别通过 `QWEN_ASR_VULKAN_WORKER_PATH` 和 `QWEN_ASR_VULKAN_MODEL_PATH` 指定其他位置。Vulkan worker/模型方案参考 [RICHARDwuxiaofei/PuriPuly-heart](https://github.com/RICHARDwuxiaofei/PuriPuly-heart)，第三方许可见 `THIRD_PARTY_NOTICES.md`。

## 使用本地模型目录

如果已经手动下载了完整模型，可以在启动前设置：

```powershell
$env:QWEN_ASR_MODEL_PATH = "D:\Models\Qwen3-ASR-1.7B"
.\run.bat
```

环境变量必须指向完整、可由 `Qwen3ASRModel.from_pretrained()` 读取的本地模型目录。应用不会自动回退到其他模型或 CPU。

中国大陆可按 Qwen3-ASR 官方推荐方式通过 ModelScope 下载，当前应用使用非 `-hf` 的 `Qwen/Qwen3-ASR-1.7B`，不需要 Forced Aligner：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -U modelscope
modelscope download --model Qwen/Qwen3-ASR-1.7B --local_dir D:\Models\Qwen3-ASR-1.7B
[Environment]::SetEnvironmentVariable("QWEN_ASR_MODEL_PATH", "D:\Models\Qwen3-ASR-1.7B", "User")
```

设置用户环境变量后应重启 PowerShell 和应用。复制其他电脑上的模型也必须复制完整目录，包括配置、processor/tokenizer 文件和所有权重分片。

## 输出规则

假设输入为 `D:\Video\meeting.mkv`，输出目录为 `E:\Transcript`，默认结果是：

```text
E:\Transcript\meeting.txt
```

若已存在，则依次使用 `meeting_001.txt`、`meeting_002.txt`。执行期间使用 `meeting.partial.txt`（编号文件对应编号 partial）；每完成一个片段就追加一个自然段、`flush` 并尝试 `fsync`。取消或异常时保留 partial 文件。最终 TXT 不含时间戳、语言标签、段号、Markdown 或软件信息。

配置保存在 `platformdirs` 返回的用户配置目录，日志保存在用户日志目录。日志轮转大小约 5MB、保留 3 个备份，并且不会记录完整识别文本。

## 常见问题

### CUDA 不可用

选择 Transformers 时，窗口会禁用“开始转写”，因为程序不会静默回退 CPU。先运行：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__); print(torch.version.cuda); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

若 `torch.version.cuda` 是 `None`，通常安装的是非 CUDA wheel；按 PyTorch 官方安装页重新安装。若有 CUDA runtime 但 `is_available()` 仍为 `False`，检查 NVIDIA 驱动、重启系统，并确认应用使用的是项目 `.venv`。

如果 CUDA 不可用但 Vulkan worker 能发现 Intel 核显，可以在界面选择 Vulkan + Intel UHD Graphics 770，保存后重启程序。两条后端互相独立。

### Vulkan 核显不可用

确认 Intel 显卡驱动正常，并检查发布目录内的 Vulkan worker。若 Q6_K 模型不存在，点击开始转写后重新选择下载线路。程序只接受 worker 返回的 Vulkan 设备类型和设备 ID，不根据名称猜测设备，也不会回退到 RTX。

### 找不到 FFmpeg / FFprobe

确认两个 exe 都在项目 `bin` 目录，或在新的 PowerShell 中能分别执行 `ffmpeg -version` 和 `ffprobe -version`。修改 PATH 后需要重新启动应用。

### MP4 无法拖入窗口

先确认扩展名是受支持的 `.mp4`。不要在“管理员 PowerShell”里启动程序：Windows 会阻止普通权限的资源管理器把文件拖进管理员程序。请关闭程序后，从资源管理器普通双击 `run.bat`，或者点击界面中的“添加文件 / 选择文件”。程序也会在检测到管理员权限时显示黄色提示。

### 启动或加载模型很慢

模型和 `.venv` 放在机械硬盘时，导入数千个 Python 小文件以及读取约 4.7 GB 权重会明显变慢。Transformers 模型现在在独立后台进程加载，窗口不会因此被阻塞；即使 PyTorch/CUDA 发生原生崩溃，也不会再直接带崩 GUI。总加载时间仍受硬盘速度影响，建议把发布版和模型都放在 SSD，或通过 `QWEN_ASR_MODEL_PATH` 指向 SSD 上的完整模型目录。

Intel 核显不能运行 PyTorch CUDA 模型。要使用核显，请选择 `transcribe.cpp（Vulkan GGUF）`、`Qwen3-ASR-1.7B Q6_K GGUF` 和实际检测到的 Intel Vulkan 设备，然后重启。核显路线需要另一份约 1.69 GB 的 Q6_K 模型；Vulkan worker 已包含在发布包中，不需要 NVIDIA CUDA，但需要正常的 Intel 显卡驱动。

### 显存不足

应用会清理 CUDA 缓存并将当前片段二分后重试。若片段已经接近 30 秒仍然 OOM，任务会停止并保留 partial 文本。请关闭其他占用显存的软件后重试。

### 模型下载后离线仍失败

先联网成功加载一次模型，或完整下载模型并设置 `QWEN_ASR_MODEL_PATH`。不能只复制单个权重文件；配置、tokenizer/processor 和全部分片也必须存在。

## 测试

基础测试不加载真实模型，也不需要 4.7GB 级权重：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

测试覆盖静音分段、两小时边界规划、短尾合并、递增输出文件名、Unicode 文件名、语言映射，以及通过依赖注入验证模型参数和结果读取。

## GitHub Actions 云编译与发布

仓库提供 `.github/workflows/windows-build.yml`：

- 手动运行 `workflow_dispatch`：在 GitHub 的 Windows runner 上测试并生成 14 天有效的审核 Artifact，不创建 Release。
- 推送 `v*` 标签：执行同一套构建，并把压缩包与 SHA-256 附加到 GitHub Release。若 CUDA 运行时导致单包接近 GitHub 的 2 GiB 单文件限制，会自动生成 7-Zip 分卷。
- 云端会安装 CUDA PyTorch、下载 FFmpeg、从固定提交构建 Vulkan worker，再执行 PyInstaller `onedir`。
- 工作流会扫描产物；发现 `.gguf`、`.safetensors` 或 `.part` 就直接失败。

GitHub 云编译不是技术上的强制要求，但对于你的发布流程更合适：本地不需要编译，构建步骤可复现，而且用户下载的是统一 ZIP。详细步骤见 `发布与云编译.md`。

## 可选本地 PyInstaller onedir 打包

源代码版验收后，可安装开发依赖并生成 onedir：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\pyinstaller.exe --clean .\QwenASRDesktop.spec
```

输出位于 `dist\QwenScribeDesktop\`。这是 onedir，不是 onefile；PyTorch 依赖很大，onedir 启动和排错更合适。两套模型权重都不会打入 EXE。spec 会携带 FFmpeg、FFprobe 和 Vulkan worker；用户首次转写时由应用下载所选模型。

## 代码结构

- `src/main_window.py`：窗口、拖放、配置绑定和线程生命周期。
- `src/queue_model.py`：独立于 Qt 的顺序批处理队列状态。
- `src/styles.py`：深色桌面主题。
- `src/transcription_worker.py`：后台任务编排、partial 持久化、取消与 OOM 细分。
- `src/media_service.py`：无 `shell=True` 的 FFprobe/FFmpeg 进程控制。
- `src/model_service.py` / `src/transformers_worker.py`：可 mock 的模型客户端及隔离式 PyTorch/CUDA 后台进程。
- `src/vulkan_model_service.py`：严格设备选择的本地 Vulkan/GGUF worker 客户端。
- `src/model_catalog.py` / `src/model_download_service.py`：外置模型检测、线路选择、续传与校验。
- `src/segmenter.py`：独立、纯函数式分段算法。
- `src/config_service.py` / `src/logging_service.py`：用户配置和轮转日志。

真实验收仍需要在目标 Windows 11 + NVIDIA GPU 上，用实际媒体验证 FFmpeg 编码支持、首次模型下载、长片段速度和 12GB 显存表现；单元测试不会替代这些硬件测试。
