# AI Project Handoff

## 1. Project Overview

QwenScribe Desktop（内部项目名 QwenASRDesktop）是面向 Windows 11 的完全本地视频/音频转文字桌面应用。用户拖入或选择媒体，程序提取音频、按静音分段，并通过本地 Qwen3-ASR-1.7B 顺序识别，最终只生成 UTF-8 TXT。目标用户是希望文件不上传云端，并使用 NVIDIA CUDA 或 Vulkan GPU 本地推理的人。

当前处于“源代码预发布检查点”阶段：核心 GUI、媒体处理、双推理后端、模型下载、partial 恢复、测试和 GitHub Actions onedir 构建流程均已实现；RTX 4070 SUPER 上的 Transformers 真机短音频闭环已通过，但长达两小时的完整任务和最新代码的云端打包产物仍需发布前验收。

## 2. Current Status

### 已完成

- PySide6 单窗口 GUI、文件/文件夹选择、整窗拖放、顺序任务队列、输出目录和语言选择。
- `src/i18n.py` 驱动的简体中文 / English 运行时界面切换；界面语言与 ASR 音频语言相互独立。
- 动态枚举 CUDA/Vulkan 设备并持久化明确设备 ID，不按显卡名称猜测或静默切换设备。
- FFprobe 校验、FFmpeg 第一音轨提取、静音检测、纯函数分段、按片段顺序识别。
- 每段立即追加并 `flush`/尽力 `fsync` 到 `.partial.txt`；成功后安全改名，取消/异常保留部分结果。
- 官方 `qwen-asr` Transformers 后端：batch size 1、不加载 Forced Aligner、不请求时间戳。
- Transformers 模型在持久独立子进程中加载，避免 PyTorch/CUDA 原生访问冲突直接带崩 Qt GUI。
- 可选 `transcribe.cpp` Vulkan GGUF 后端，通过独立 worker 支持实际枚举到的核显/独显。
- 国内/国际模型下载线路、断点续传、固定 revision/文件大小，关键权重带 SHA-256 校验。
- platformdirs JSON 配置、轮转日志、Windows 无黑框外部进程、取消 FFmpeg。
- pytest 基础测试和 GitHub Actions Windows onedir 构建/Release 工作流。

### 基本完成但仍需验证

- 最新 Transformers 隔离进程已在 RTX 4070 SUPER 上实际加载并识别 8 秒媒体，但修改后的完整 GUI 长任务尚未重新跑完。
- Vulkan 后端已有设备严格选择和服务测试；发布前仍应在目标 Intel/NVIDIA 驱动上重新做真实识别。
- PyInstaller spec 已兼容打包后的 `--transformers-worker` 入口，但最新代码尚未生成并手测 onedir 包。
- GitHub Actions 工作流已写好，首次上传后仍需手动运行一次并核对 Artifact。

### 未完成

- 尚无正式版本号、Release 和签名安装程序。
- 尚未完成干净 Windows 11 电脑上的从零安装/离线复测。
- 项目自身许可证尚未确定；第三方组件说明见 `THIRD_PARTY_NOTICES.md`。

### 已知 Bug / 限制

- Transformers 正在执行某个 CUDA 片段时只能等待该片段结束后响应取消；不会强杀 CUDA kernel。
- 切换推理后端或 GPU 后需要重启应用，让持久模型进程绑定新设备。
- 管理员权限启动的应用不能接收普通权限资源管理器的文件拖放，这是 Windows 权限隔离行为。
- 模型和 `.venv` 位于机械硬盘时首次导入会很慢；模型放 SSD 只能加速权重读取，完整项目/虚拟环境也放 SSD 才能最大化改善导入。

### 暂不准备做

- 云端 ASR、文件上传、Web 后端、Whisper、vLLM、Forced Aligner、SRT/VTT、时间戳和 PyInstaller onefile。

## 3. Architecture

```text
PySide6 MainWindow (GUI main thread)
  | Qt signals
  v
TranscriptionWorker (persistent QThread)
  |-- MediaService -> FFprobe / FFmpeg child processes
  |-- Segmenter -> pure boundary calculation
  |-- ModelService -> persistent Python Transformers subprocess -> CUDA GPU
  `-- VulkanModelService -> authenticated loopback worker -> Vulkan GPU

ModelDownloadService -> ModelScope/Hugging Face/hf-mirror (download only)
ConfigService / LoggingService -> platformdirs user directories
Output -> UTF-8 TXT and crash-safe partial TXT
```

没有数据库、远程业务 API 或监听固定端口。正常转写不联网；仅缺少模型并经用户选择下载线路时访问模型站点。Transformers 子进程使用 stdin/stdout JSON 行通信；Vulkan worker 使用仅本机回环地址的临时端口和会话鉴权。

## 4. Important Files

`app.py`

- GUI 入口、后端实例选择、打包后 Transformers worker 入口和原生崩溃日志启用。

`src/main_window.py`

- UI、拖放、队列、设置持久化、模型下载交互和 QThread 生命周期。改 GUI/批处理行为先读这里。

`src/transcription_worker.py`

- 完整任务编排、进度、partial 保存、取消、错误恢复和 OOM 递归细分。

`src/media_service.py` / `src/segmenter.py`

- FFmpeg/FFprobe 子进程控制与分段边界算法。媒体格式、时长或切片问题先读这里。

`src/model_service.py` / `src/transformers_worker.py`

- 官方 Transformers 后端客户端和隔离模型进程。CUDA 加载/崩溃/OOM 问题先读这里。

`src/vulkan_model_service.py`

- Vulkan worker 协议、严格设备选择和 GGUF 推理。

`src/model_catalog.py` / `src/model_download_service.py`

- 外置模型查找顺序、固定 revision、国内/国际下载和完整性校验。

`src/config_service.py` / `src/logging_service.py`

- 用户 JSON 配置与轮转日志位置。

`src/i18n.py`

- 无外部依赖的界面翻译资源、ASR 语言显示名和常见运行状态翻译。增加界面语言时优先扩展这里。

`QwenASRDesktop.spec` / `.github/workflows/windows-build.yml`

- PyInstaller onedir 内容和 GitHub Windows 云构建/Release 流程；模型权重不得进入产物。

`README.md` / `使用说明.md` / `发布与云编译.md`

- 安装、使用、故障排查和发布操作说明。

## 5. Main Data Flow

### 转写

用户添加媒体并开始队列
→ GUI 将 `TranscriptionTask` 通过 Qt signal 交给持久 QThread
→ FFprobe 验证第一音轨和时长
→ FFmpeg 提取 16 kHz 单声道 PCM WAV 到独立临时目录
→ FFmpeg `silencedetect`，纯函数计算约 180 秒边界
→ 加载或复用所选后端模型
→ 每次只创建一个片段并识别
→ 每段文本立即写入 partial
→ 全部成功后安全改名为递增命名的最终 `.txt`
→ `finally` 清理临时音频。

### 模型选择/下载

GUI 选择 Transformers 或 Vulkan、模型和明确设备 ID
→ 保存用户配置
→ 后端/设备改变时提示重启
→ 若本地模型不完整，用户选择“中国境内”或“国际”线路
→ 后台下载 `.part`、续传和校验
→ 安装到 platformdirs 用户数据目录
→ 后续可断网使用。

## 6. Important Design Decisions

- 所有耗时媒体工作和调度留在 QThread；QWidget 只能由主线程更新，后台只能发 Qt signal。
- Transformers 模型必须在独立进程主线程加载。此前在 Windows 的长生命周期 QThread 中构造 Qwen/PyTorch 模型发生过 `0xc0000005` 原生访问冲突；不要为了“简化”重新内嵌进 GUI 进程。
- Vulkan worker 同样保持进程隔离。显式请求设备时，实际设备 ID 不一致必须失败，禁止静默回退。
- 后端/设备切换后重启是有意设计，避免在同一进程里反复初始化不同 GPU runtime。
- 不一次加载完整长音频或多个长片段到 GPU；batch size 固定 1，并按时长而非片段数计算识别进度。
- 提取后的完整音频使用 PCM WAV 作为真实时长来源。无容器 AAC 等格式的 FFprobe 估算可能不准，不能再用原媒体估算值切最后一段。
- 不使用重叠分段，避免重复文本；短尾尽可能并入前段；OOM 才递归二分至约 30 秒下限。
- partial 文件是崩溃恢复机制，异常/取消时不能删除。
- 模型必须外置：`.gitignore`、spec 和 CI 都禁止把 GGUF/safetensors 打进源码或 EXE。
- FFmpeg 调用必须使用参数列表、`shell=False` 默认行为和 Windows 无窗口标志，以兼容 Unicode/空格路径。

## 7. Configuration / Environment

Windows 用户配置：`%LOCALAPPDATA%\QwenASRDesktop\config.json`。键包括 `last_input_directory`、`output_directory`、`selected_language`、`ui_language`、`window_geometry`、`inference_backend`、`cuda_device_id`、`vulkan_device_id`。

日志：`%LOCALAPPDATA%\QwenASRDesktop\Logs\QwenASRDesktop.log` 及 native crash log。用户配置、日志、partial、模型和下载缓存均不得提交。

环境变量：

- `QWEN_ASR_MODEL_PATH`：可选，完整官方 Transformers 模型目录。
- `QWEN_ASR_VULKAN_MODEL_PATH`：可选，Q6_K GGUF 文件路径。
- `QWEN_ASR_PORTABLE_ROOT`：程序内部用于定位便携版外置模型，通常不需手动设置。

没有 API Key、Token、密码或外部数据库配置。模型来源和固定 revision 见 `src/model_catalog.py`。

## 8. How to Run

Windows 11、64 位 Python 3.12 和 NVIDIA CUDA 路线：

```powershell
cd <你的路径>\QwenASRDesktop
Set-ExecutionPolicy -Scope Process Bypass
.\install_windows.ps1
.\run.bat
```

日常已有环境只需 `run.bat`。FFmpeg/FFprobe 可放 `bin` 或系统 PATH。首次选择某后端且模型缺失时，按 GUI 选择国内或国际下载线路。

## 9. How to Verify

不下载模型的基础检查：

```powershell
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe -m pytest -q
.\run.bat --check
```

发布前还应手动验证：普通权限启动、MP4 拖放、CUDA/Vulkan 设备选择、短媒体真实输出、取消后 partial、同进程第二个任务复用模型、无音轨错误、中文/空格路径。然后在 GitHub Actions 手动运行 `Windows onedir build`，下载 Artifact，在干净 Windows 11 上测试 EXE。

## 10. Known Problems / Technical Debt

- PyInstaller 的最新 Transformers 子进程入口需要首个云端 onedir Artifact 做真实验证。
- 两小时典型媒体尚未在本次检查点后完整跑完，长任务速度和取消行为仍需验收。
- Python/qwen-asr 依赖较重；若整个项目和 `.venv` 位于 HDD，启动导入慢。当前开发机仅模型通过目录联接移动到 L 盘 NVMe。
- 模型下载器依赖镜像可用性；网络中断可续传，但镜像服务状态不受项目控制。
- Vulkan worker 来自固定的 PuriPuly-heart commit；升级协议/二进制时必须同步客户端契约和第三方通知。
- 缺少应用自身许可证、代码签名和正式安装器。

## 11. Next Recommended Tasks

### P0

- 初始化并安全发布 GitHub 仓库，运行一次手动 GitHub Actions onedir 构建。
- 下载 Artifact，在普通权限 Windows 11 上验证 GUI 启动和 Transformers worker 打包入口。

### P1

- 用较长真实媒体分别验证 CUDA、取消/partial、第二任务模型复用；如计划支持核显，再复测 Vulkan。
- 确定项目许可证，并准备首个版本标签和 Release 说明。

### P2

- 将开发项目和 `.venv` 一并迁移 SSD 或使用发布版，记录冷启动时间。
- 根据真实用户错误日志完善子进程崩溃提示和恢复体验。

## 12. Instructions for the Next AI

开始工作时：

1. 首先阅读 `AI_HANDOFF.md`。
2. 然后阅读 `README.md`。
3. 查看 `git status`。
4. 查看最近 5～10 条 git commit。
5. 根据当前任务，只阅读本文件指出的相关代码。
6. 不要无目的扫描或重新阅读整个仓库。
7. 修改前先确认现有架构和设计决定。
8. 不要删除看起来多余但本文注明有兼容或崩溃隔离作用的代码。
9. 完成修改后更新 `AI_HANDOFF.md` 中受影响的部分。
10. 不要提交模型、`.venv`、日志、用户媒体、partial 文件或任何凭据。

## 13. Last Handoff State

- 日期：2026-08-29
- branch：`main`
- 基础检查点 commit：`9ee4094c979c7e9f48c8c7d76e7260564423d154`；当前 HEAD 请运行 `git rev-parse HEAD`
- 阶段：QwenScribe Desktop v1.0.0 发布候选，等待首次 GitHub 云构建审核
- 未提交修改：发布提交前以 `git status` 为准
- 最后验证：`compileall` 通过；pytest 29 项通过（含 i18n GUI 切换）；RTX 4070 SUPER 实际加载本地 Qwen3-ASR-1.7B 成功（16.33 秒）；从真实 MP4 截取 8 秒音频完成转写（加载加识别 23.50 秒，58 字符，Chinese）
- 未执行：最新 GUI 完整长任务、最新 PyInstaller onedir 构建、GitHub Actions、干净机器安装验收
