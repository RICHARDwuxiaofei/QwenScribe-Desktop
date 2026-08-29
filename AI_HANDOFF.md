# AI Project Handoff

## 1. Project Overview

QwenScribe Desktop（内部项目名 QwenASRDesktop）是面向 Windows 11 的完全本地视频/音频转文字桌面应用。用户拖入或选择媒体，程序提取音频、按静音分段，并通过本地 Qwen3-ASR-1.7B 顺序识别，最终只生成 UTF-8 TXT。目标用户是希望文件不上传云端，并使用 NVIDIA CUDA 或 Vulkan GPU 本地推理的人。

当前处于“v1.0.0 发布候选”阶段：核心 GUI、媒体处理、双推理后端、模型下载、partial 恢复、测试和 GitHub Actions onedir 构建流程均已实现；RTX 4070 SUPER 上的 Transformers 真机短音频闭环已通过，Windows 云端 onedir 构建及 Artifact 上传也已通过。下一步是下载并检查 Artifact、做普通权限 Windows 启动验收，然后创建 `v1.0.0` tag/Release。

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
- 公开仓库已建立并推送到 `https://github.com/RICHARDwuxiaofei/QwenScribe-Desktop`。
- GitHub Actions 审核构建 `33216786493` 已成功：29 项测试、FFmpeg/FFprobe、Vulkan worker、PyInstaller onedir、模型排除检查和 Artifact 上传均通过。

### 基本完成但仍需验证

- 最新 Transformers 隔离进程已在 RTX 4070 SUPER 上实际加载并识别 8 秒媒体，但修改后的完整 GUI 长任务尚未重新跑完。
- Vulkan 后端已有设备严格选择和服务测试；发布前仍应在目标 Intel/NVIDIA 驱动上重新做真实识别。
- 云端 onedir Artifact 已生成，但尚未下载到本机解包并手测 GUI/`--transformers-worker` 入口。
- 尚未在干净 Windows 11 电脑上验证该 Artifact 的首次模型下载和真实转写。

### 未完成

- 代码版本已设为 `1.0.0`，但尚未创建 `v1.0.0` tag/GitHub Release；也没有签名安装程序。
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

- 首个云端 onedir Artifact 已成功生成，但最新 Transformers 子进程入口仍需下载后做真实启动验证。
- 两小时典型媒体尚未在本次检查点后完整跑完，长任务速度和取消行为仍需验收。
- Python/qwen-asr 依赖较重；若整个项目和 `.venv` 位于 HDD，启动导入慢。当前开发机仅模型通过目录联接移动到 L 盘 NVMe。
- 模型下载器依赖镜像可用性；网络中断可续传，但镜像服务状态不受项目控制。
- Vulkan worker 来自固定的 PuriPuly-heart commit；升级协议/二进制时必须同步客户端契约和第三方通知。
- 缺少应用自身许可证、代码签名和正式安装器。

## 11. Next Recommended Tasks

### P0

- 从成功运行 `33216786493` 下载 `QwenScribe-Desktop-Windows-x64` Artifact，核对其中的 SHA-256、分卷完整性、EXE/FFmpeg/Vulkan worker 和模型排除情况。
- 在普通权限 Windows 11 上解压并验证 GUI 启动、语言切换、拖放、设备枚举和 Transformers worker 打包入口。
- 验证通过后，在最终 handoff/docs 提交上创建并推送 `v1.0.0` tag；监控 tag 构建自动生成 GitHub Release，禁止 force push。

### P1

- 用较长真实媒体分别验证 CUDA、取消/partial、第二任务模型复用；如计划支持核显，再复测 Vulkan。
- 确定项目许可证；补齐/审核 v1.0.0 中英文 Release 说明。

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
- 本次交接前代码 commit：`4742c052d9c08c6d9368ab37ed1206a0149761e7`（本文件随后会有一个 handoff 提交）
- 阶段：QwenScribe Desktop v1.0.0 发布候选；云构建已通过，尚未打 tag/发布 Release
- GitHub：`https://github.com/RICHARDwuxiaofei/QwenScribe-Desktop`（public），remote `origin`，禁止 force push
- 云构建：Actions run `33216786493` 成功，job `99002098086`，耗时 28m46s；Artifact `QwenScribe-Desktop-Windows-x64`，ID `9704253084`，GitHub 外层归档大小 `2254013387` bytes，尚未下载验包
- workflow 修复：pytest 使用 `--basetemp=.pytest_tmp` 且 `.gitignore` 已忽略；FFmpeg 从 Chocolatey 实际安装目录递归取二进制；大型包直接使用 1800 MiB 分卷 7z，避免先压超大 ZIP 再重压
- 未提交修改：提交本次 handoff 后应为干净工作树；新 AI 必须先运行 `git status` 和 `git log -10 --oneline`
- 最后验证：本地 pytest 29 项通过（使用系统 Python 3.12 加载现有 `.venv` site-packages，因为 `.venv` 启动器记录的旧 Python 路径失效）；云端 pytest 29 项通过；云端 FFmpeg/Vulkan/PyInstaller/模型排除/Artifact 上传通过；RTX 4070 SUPER 实际加载本地 Qwen3-ASR-1.7B 成功（16.33 秒）；真实 MP4 的 8 秒音频完成转写（加载加识别 23.50 秒，58 字符，Chinese）
- 未执行：下载并解包本次 Artifact、打包 EXE 真机启动、最新 GUI 完整长任务、干净机器安装验收、`v1.0.0` tag 和 GitHub Release

## 14. Release packaging size decision handoff (2026-08-29)

> 本节是当前发布体积讨论的最新交接，优先于第 11 节中“验收后立即打 tag”的旧计划。体积架构没有得到用户确认前，不得创建 tag、Release 或新代码提交。

### 当前事实

- 用户指定的发布验收代码基线是 `c1aca48`。本轮只允许更新文档；不得 reset、rebase、force push、修改源码/工作流、创建 commit 或创建 `v1.0.0` tag。
- 记录时本地分支为 `main`，HEAD 为 `9e1734f`（`c1aca48` 的后续提交），工作树原本干净；本次文档改动会使工作树出现有意的文档差异，代码和 workflow 内容不应改变。
- GitHub 源码仓库 `RICHARDwuxiaofei/QwenScribe-Desktop` 的 API `size` 约为 90 KB；当前 Git 跟踪文件实际合计约 226,742 bytes。仓库小是正常的：`.venv`、模型、下载缓存和 EXE 均被 `.gitignore` 排除，没有把模型提交到 Git。
- 本机开发目录约 10.34 GiB，主要是 `.venv` 约 5.71 GiB、CUDA PyTorch site-packages 约 4.11 GiB、`downloads` 中的 PyTorch wheel 约 2.56 GiB、`models` 中的 Q6_K GGUF 约 1.58 GiB，以及 `bin` 中约 424 MiB 的 FFmpeg/FFprobe 和约 74 MiB 的 Vulkan worker。这些是开发环境/外置模型，不等于 GitHub 仓库大小。
- Actions run `33216786493` 成功，Artifact ID `9704253084`，名称 `QwenScribe-Desktop-Windows-x64`。GitHub 记录的外层归档大小为 `2,254,013,387` bytes（约 2.10 GiB），digest 为 `7d15a932ce2ae5d7ba6f790f58c7968efefd8d39994b2b72776bdcbb9e184391`。当前尚未完成本地完整下载、SHA-256、解包或 EXE 真机验收；不要把这次云构建成功当作发布验收通过。
- 之前的下载因 Azure/GitHub 签名链路过慢/过期中断，留下的临时部分文件（若仍存在）是 `D:\CODE\TTS\release-validation-33216786493\artifact-9704253084.zip`，约 522,665,984 bytes；它不是完整 Artifact，不能用于验收。用户可在下一次对话中手动下载到新的干净目录。

### 为什么当前包很大

- `QwenASRDesktop.spec` 同时收集 `qwen_asr`、PySide6、Transformers/PyTorch 路线所需运行时、`bin/ffmpeg.exe`、`bin/ffprobe.exe` 和 `bin/PuriPulyHeartGpuWorker.exe`。模型文件明确外置，CI 还会递归拒绝 `.gguf`、`.safetensors` 和 `.part`。
- workflow 安装 `torch==2.11.0+cu128`，因此为了支持 NVIDIA CUDA/Transformers，PyInstaller 需要带上相当大的 CUDA/PyTorch 原生 DLL。开发环境中仅 `torch` 就约 4.11 GiB；这不是误把整个 `.venv` 上传，而是双后端自包含包的主要体积来源。
- 两个静态 FFmpeg 文件合计约 444,293,120 bytes（约 424 MiB），Vulkan worker 约 74 MiB。即使去掉 CUDA，若仍把 FFmpeg 静态打包，Vulkan 基础包也不会自然缩小到约 160 MiB。
- “把 onedir 改成 onefile”只改变用户看到的压缩/解压方式，不会消除运行时 DLL；不能作为体积优化方案。

### 与 PuriPuly-heart 的可比信息

- `https://github.com/kapitalismho/PuriPuly-heart` 当前默认分支为 `dev`，GitHub 仓库 API size 约 304 MiB；这不是它的发布安装包大小。
- PuriPuly `v2.5.0` 的 `PuriPulyHeart-Setup-2.5.0.exe` 为 168,998,431 bytes（约 161 MiB）。其公开依赖是 ONNX Runtime/Sherpa 等 Vulkan/CPU 路线，没有当前项目这样完整的 PyTorch CUDA 栈；模型按应用逻辑下载/管理。因此“源仓库大小、开发目录大小、发布安装包大小”必须分开比较。
- 参考页面：PuriPuly README 的本地模型说明和 [v2.5.0 Release](https://github.com/kapitalismho/PuriPuly-heart/releases/tag/v2.5.0)。

### 待讨论的三种发布架构

1. **默认 Vulkan/GGUF，CUDA/Transformers 单独大型包（推荐先讨论）**：默认下载面向 Intel/AMD/NVIDIA Vulkan 的 GGUF 版；另发 `CUDA-Transformers` 可选包。优点是默认用户不承担 CUDA 体积，模型仍可首次下载；代价是维护两条构建/验收矩阵。若默认包仍携带静态 FFmpeg，体积下限仍约 424 MiB 加其余运行时。
2. **小启动器/Bootstrapper**：只发布一个很小的启动器，首次运行检测 GPU/驱动，按选择下载 Vulkan 或 CUDA 运行时、模型和 FFmpeg，逐项做 HTTPS、SHA-256/签名校验并缓存。优点是首包最小；代价是首次联网、下载失败恢复、镜像/CDN、安全更新和离线使用都要设计，不能只把现有 EXE 再套一层壳。
3. **Vulkan-only + 外部/精简媒体运行时**：去掉 Transformers/CUDA，仅保留 GGUF/Vulkan，并要求系统 FFmpeg 或改用更小的定制 FFmpeg。最接近 PuriPuly 体积，但牺牲“解压即用”的媒体依赖和 CUDA 用户覆盖面。

可作为补充的低风险测量项：对已构建目录做 PyInstaller import graph、DLL 依赖和体积清单，确认是否有可安全排除的未使用模块；不能凭文件名删除 CUDA DLL，也不能破坏进程隔离或 Vulkan worker 协议。

### 下一次对话的讨论顺序

1. 先读本文件和 `RELEASE_PACKAGING_SIZE_DISCUSSION.md`，确认事实与限制；只做定向检查，不扫描整个仓库。
2. 先决定产品目标：默认 GPU 覆盖（Vulkan 还是 CUDA）、是否必须离线、是否必须自带 FFmpeg、目标首包/安装后体积，以及是否接受两个下载包。
3. 用决策矩阵比较“默认 Vulkan 包 + 可选 CUDA”“Bootstrapper”“Vulkan-only + 系统 FFmpeg”，分别记录下载体积、安装后体积、首次启动、离线能力、故障恢复、安全校验、维护成本和支持的 GPU。
4. 方案得到用户确认后，才设计最小的 packaging/workflow 改动；先构建和清单检查，再做干净目录/普通权限的真实 EXE 验收。验收失败先记录错误和原因，不得立即打 tag。
5. 只有完整 Artifact 下载、外层 ZIP SHA-256 与 GitHub digest 一致、解压结构完整、EXE 真机验收通过且用户再次确认后，才讨论 `v1.0.0` 发布；本交接阶段不得自行创建或推送 tag。

### 发布前不可省略的验收

- 在全新、非开发目录解压；不从源码、`.venv`、本机 PATH 或其他资源补文件。
- EXE 能启动并显示 GUI；FFmpeg/FFprobe 实际可调用；Vulkan/GPU 枚举和显式设备选择正确；模型发现、下载、校验和加载流程可用；用真实音频完成一次转写。
- 运行时路径不能指向开发目录，不能依赖本机 Python；检查包内模型排除规则和所有随包 DLL/worker 的来源。
- 对每个候选 SKU 分别记录压缩包大小、解压后大小、启动时间、首次下载行为、错误日志和支持的 GPU/驱动范围。

## 15. Windows SKU packaging implementation (2026-08-29)

> 本节覆盖第 14 节中“只讨论、不得改代码/commit”的历史限制。当前工作分支为 `codex/reduce-windows-package-size`；不要 reset、rebase、force push 或覆盖已有工作。

- 默认 SKU：`QwenScribe-Vulkan-Windows-x64`。只包含 Vulkan/GGUF、固定 worker、Qt/Python 和 FFmpeg/FFprobe；不安装或打包 torch、torchgen、Transformers、qwen-asr、CUDA、cuDNN、cuBLAS，也不包含模型。
- CUDA SKU：`QwenScribe-CUDA-Windows-x64`。只包含 CUDA/Transformers 路线和独立 Transformers 子进程；不包含 Vulkan worker，也不包含模型。
- `src/build_config.py` 是 SKU 能力的唯一声明点。PyInstaller runtime hook 固定 `QWENSCRIBE_BUILD_VARIANT`；UI 不会显示当前 SKU 不含的后端。若用户持久化了另一 SKU 的后端，显示明确提示，不静默改 GPU 或覆盖配置。
- `requirements-common.txt`、`requirements-vulkan.txt`、`requirements-cuda.txt`、`requirements-dev.txt` 已拆分。Vulkan CI 必须在没有 torch/Transformers/qwen-asr 的全新环境中通过导入、测试和包内 `--check`。
- `QwenASRDesktop.spec` 是参数化 onedir spec：设置 `QWENSCRIBE_BUILD_VARIANT=vulkan|cuda|full`。`full` 仅保留为显式诊断用途，并非普通 Artifact。
- `scripts/report_package_size.ps1` 会输出 `packaging-size-report.json` 和 `.md`，区分 Git 跟踪大小、包解压大小、压缩 Artifact、FFmpeg、外置模型与首次可用下载量，并拒绝模型、缓存、日志和媒体。
- Windows workflow 已改为两个 SKU job；每个 Artifact 同时上传 archive SHA-256、`artifact-manifest.json` 和 size report。CI 在新目录检查 variant、内置 FFmpeg/FFprobe、短 WAV、`silencedetect` 和包边界。GitHub runner 不含真实 GPU，因此真实枚举、模型下载/离线、真实音频转写仍是人工验收项。
- 本机 Vulkan 实测（标准 ZIP，非 CI 7z）：解压 `653.81 MiB`；压缩 `253.97 MiB`；FFmpeg/FFprobe 解压 `423.71 MiB`；worker `74.17 MiB`。已达压缩 Artifact `<500 MiB` 硬目标和 `<300 MiB` 理想目标，因此当前保留自包含 FFmpeg；外置 Q6_K 模型约 `1.69 GB`，首次真正可用下载量约 `1.87 GB`。这不是干净 Windows 或真实 GPU 完整验收。
- 已保留：Transformers 独立子进程、Vulkan 独立 worker、显式 GPU ID 严格匹配、batch size 1、partial 恢复、参数列表 FFmpeg/无窗口子进程、模型外置、TXT/分段语义。
