# QwenScribe Desktop：发布体积与后端拆分方案讨论材料

生成日期：2026-08-29  
用途：交给下一次对话或网页端 GPT，先讨论发布架构，再决定是否修改 packaging/workflow。  
当前状态：只整理事实和方案；本文件不代表已完成 Artifact 验收，也不代表可以发布 `v1.0.0`。

## 1. 先给结论

现在看到的三个“大小”不是同一个东西：

| 对象 | 当前测量 | 说明 |
|---|---:|---|
| GitHub 源码仓库 API `size` | 约 90 KB | Git 对象的服务器压缩用量，不包含被 `.gitignore` 排除的开发环境、模型和构建产物 |
| 当前 Git 跟踪文件 | 约 226,742 bytes | 源码、测试、文档、配置和少量占位文件；没有模型、`.venv` 或 EXE |
| 本机开发目录 | 约 10.34 GiB | `.venv`、PyTorch wheel、外置 GGUF、FFmpeg 和开发缓存等的总和 |
| Actions Artifact 外层归档 | 2,254,013,387 bytes，约 2.10 GiB | run `33216786493` 的 Artifact `9704253084`；这是自包含双后端 Windows 发布候选包的 GitHub 外层归档大小 |

因此，GitHub 仓库只有约 90 KB 并不表示“没有上传编译结果”；源码仓库和 Release/Actions Artifact 是两条不同的存储链路。当前 Artifact 也不是把整个本机 `.venv` 或模型目录直接上传的证据：workflow 只归档 `dist`，并主动拒绝 `.gguf`、`.safetensors`、`.part`。不过 Artifact 的本地完整下载、哈希、解压和 EXE 验收尚未完成，所以仍需在发布前检查实际内容。

## 2. 当前项目到底构建了什么

当前项目不是只有一个轻量 STT 前端，而是一个 Windows x64 自包含 onedir 发布候选，目标同时覆盖：

- PySide6 GUI；
- Transformers/Qwen-ASR + PyTorch CUDA 后端；
- Vulkan/GGUF 后端，以及隔离的 `PuriPulyHeartGpuWorker.exe`；
- 随包的真实 `ffmpeg.exe` 和 `ffprobe.exe`；
- 模型外置，首次按 GUI 逻辑下载到用户数据目录。

当前 `QwenASRDesktop.spec` 的关键行为：

- `collect_all("qwen_asr")`，并分析 `app.py`、Qt 数据和隐藏导入；
- 如果存在则把 `bin/ffmpeg.exe`、`bin/ffprobe.exe`、`bin/PuriPulyHeartGpuWorker.exe` 放入发布目录；
- 生成 `QwenScribeDesktop.exe` 的 PyInstaller onedir 输出；
- 模型不打包，模型路径由配置/环境变量/用户数据目录提供。

当前 Windows workflow 的关键行为：

- 安装 `torch==2.11.0+cu128`、`PySide6`、`qwen-asr` 和测试依赖；
- 从 Chocolatey 的真实安装目录递归寻找 FFmpeg，而不是复制 shim；
- 构建 Vulkan worker；
- 运行 29 个 pytest；
- PyInstaller 后递归扫描发布目录，拒绝 `.gguf`、`.safetensors`、`.part`；
- 用 7z 分卷归档并上传 review Artifact；tag 构建才会走 Release 附件路径。

## 3. 2.1 GiB 主要来自哪里

### 开发目录与发布包要分开

本机开发目录约 10.34 GiB，其中：

- `.venv`：约 5.71 GiB；
- `site-packages/torch`：约 4.11 GiB，`torch/lib` 约 3.99 GiB；
- `downloads`：约 2.56 GiB，主要是 PyTorch wheel；
- `models`：约 1.58 GiB，当前 Qwen3-ASR-1.7B Q6_K GGUF；
- `bin`：约 0.49 GiB，其中 FFmpeg/FFprobe 合计约 424 MiB，Vulkan worker 约 74 MiB。

这些数字会相互包含（例如 `.venv` 已包含 torch），不能直接相加当成 GitHub 包大小；它们用于定位体积来源。

### 发布候选中的合理大头

1. **PyTorch/CUDA 原生运行时**：只有在保留 Transformers/CUDA 后端时才需要。这是最重要的可选大头，不是“误上传模型”。
2. **静态 FFmpeg/FFprobe**：两个文件合计约 444,293,120 bytes，约 424 MiB。它们使“解压即用”成立，但即使完全删除 CUDA，Vulkan 包仍不会自动接近 161 MiB。
3. **Vulkan worker**：约 74 MiB；保留 Vulkan/GGUF 时属于功能运行时。
4. **Qt/Python/PyInstaller 运行时**：需要做 import graph/DLL 清单后才能判断是否有可安全排除项；不能把整个 `.venv` 目录大小等同于最终包，也不能只按 DLL 名字猜测依赖。

当前证据更支持“项目选择了双后端自包含路线”，而不是“把不该上传的模型或整个开发目录上传了”。完整 Artifact 解压后仍必须用文件清单验证这一点。

## 4. 为什么 PuriPuly 看起来小很多

公开可比数据（查询日期 2026-08-29）：

- PuriPuly-heart GitHub 仓库 API size 约 304 MiB；这是 Git 仓库体积，不是安装包。
- PuriPuly `v2.5.0` 的 `PuriPulyHeart-Setup-2.5.0.exe` 为 168,998,431 bytes，约 161 MiB。
- PuriPuly 的公开依赖路线是 ONNX Runtime/Sherpa 等 Vulkan/CPU 运行时，并没有当前项目为 Transformers 准备的完整 PyTorch CUDA 栈；模型按应用逻辑下载/管理。
- 参考：[PuriPuly-heart 仓库](https://github.com/kapitalismho/PuriPuly-heart)、[PuriPuly v2.5.0 Release](https://github.com/kapitalismho/PuriPuly-heart/releases/tag/v2.5.0)。

所以不能拿“PuriPuly 安装器 161 MiB”直接推断当前双后端包也应为同样大小。要接近它，首先要选择相近的运行时边界：Vulkan/GGUF（或 ONNX/Sherpa）为默认路线，并处理 FFmpeg 是否随包携带。

## 5. 三种候选发布方案

### 方案 A：默认 Vulkan/GGUF，CUDA/Transformers 单独大型包

建议作为第一轮产品方案讨论的基准。

默认发布：

- `QwenScribe-Vulkan-GGUF-Windows-x64`；
- 面向 Intel/AMD/NVIDIA 的 Vulkan 驱动路线；
- 模型首次下载，下载后可断网使用；
- 不携带 PyTorch/CUDA/Transformers 大栈。

可选发布：

- `QwenScribe-CUDA-Transformers-Windows-x64`；
- 面向 NVIDIA CUDA 用户；
- 保留当前 Transformers 能力和相应大体积运行时。

优点：默认下载明显变小，功能边界清楚，用户不需要为不用的 CUDA 付费。  
代价：两个 SKU 都要有独立构建、测试、说明和支持矩阵。  
关键限制：若 Vulkan 包仍静态携带当前 FFmpeg/FFprobe，单这两个文件就约 424 MiB，不能承诺“接近 161 MiB”。

### 方案 B：小启动器，首次按 GPU 下载运行时和模型

发布一个几 MB 级别的 Bootstrapper：

1. 检查 Windows x64、驱动和可用 GPU；
2. 用户确认 Vulkan 或 CUDA 路线（或按明确规则推荐）；
3. 从固定 HTTPS/CDN 下载对应 runtime、FFmpeg、worker 和模型；
4. 对每个文件做 SHA-256，最好再做签名/签名链校验；
5. 原子安装到用户数据目录，支持 `.part` 续传、失败恢复、版本回滚；
6. 后续离线启动已缓存的后端。

优点：首次下载最小，后端可按设备选择。  
代价：首次必须联网；要维护 CDN/镜像、校验、权限、更新、清理和离线行为，风险和工程量都高于单一压缩包。不能只把现有大 EXE 再套一层启动器就达到目标。

### 方案 C：Vulkan-only + 外部或精简 FFmpeg

只保留 Vulkan/GGUF，且：

- 要么要求用户已有 FFmpeg/FFprobe；
- 要么提供更小的定制 FFmpeg（只保留项目实际需要的编解码器）；
- 去掉 PyTorch/CUDA/Transformers 包和相关测试矩阵。

优点：最接近 PuriPuly 的发布边界。  
代价：系统依赖会破坏“任意电脑解压即用”，定制 FFmpeg 需要重新验证媒体覆盖率；CUDA 用户不再由默认包覆盖。

### 不应作为主要方案的做法

- **只改 onefile**：通常只改变压缩和启动时解压方式，不减少总运行时体积。
- **按文件名盲删 DLL**：可能造成导入、GPU 初始化或子进程崩溃；必须基于依赖分析和干净机回归。
- **把模型塞进默认包**：会增加下载体积，也与当前模型外置、首次下载设计冲突。

## 6. 需要网页端 GPT 一起回答的决策问题

请按以下顺序讨论，不要先改代码：

1. **产品默认后端**：默认面向所有 Vulkan GPU，还是只优先 NVIDIA CUDA？是否必须同时支持 Intel/AMD？
2. **体积目标**：目标是“下载包 < 300 MiB”“接近 PuriPuly 161 MiB”，还是只希望从 2.1 GiB 降到可接受范围？要分别定义压缩包和解压后大小。
3. **FFmpeg 策略**：必须自包含、允许检测系统 FFmpeg，还是接受按需下载/定制构建？
4. **网络/离线**：首次运行是否强制联网？模型和 runtime 是否允许用户手动导入？断网时已有缓存能否继续工作？
5. **发布形态**：两个独立包、一个 Bootstrapper，还是先保持单包并做可测量的 DLL 精简？
6. **维护边界**：是否愿意维护 Vulkan 与 CUDA 两条构建、测试、Issue 支持和发布说明？
7. **兼容范围**：Windows 11 x64 是否固定？最低 Vulkan 驱动、NVIDIA CUDA 驱动、磁盘空间和内存要求是什么？
8. **安全**：下载源、固定版本、SHA-256、签名、回滚和缓存目录如何定义？

建议让网页端 GPT 最终输出：

- 一页决策表；
- 推荐方案及不选其他方案的原因；
- 预计包大小的“已知下限/待测量项”，不要编造精确数字；
- 最小代码/workflow 变更清单；
- 构建、清洁目录验收和回滚计划；
- 需要用户最终确认的产品决策。

## 7. 可直接复制给网页端 GPT 的讨论提示词

```text
我在 Windows x64 上维护 QwenScribe Desktop，一个 PySide6 的本地 STT 桌面程序。请先做发布架构决策，不要直接改代码。

已知事实（截至 2026-08-29）：
- GitHub 源码仓库 API size 约 90 KB；Git 跟踪文件约 226,742 bytes。模型、.venv、下载缓存和 EXE 不在 Git 中。
- 本机开发目录约 10.34 GiB，主要是 CUDA PyTorch 开发环境、外置 Q6_K GGUF 模型、静态 FFmpeg/FFprobe 和 Vulkan worker。
- Actions run 33216786493 成功，Artifact 9704253084 的 GitHub 外层归档大小为 2,254,013,387 bytes（约 2.10 GiB）。workflow 安装 torch==2.11.0+cu128，PyInstaller 同时打包 PySide6、Transformers/CUDA 运行时、Vulkan worker、真实 ffmpeg.exe/ffprobe.exe；明确排除 .gguf/.safetensors/.part。
- PuriPuly-heart v2.5.0 安装器约 168,998,431 bytes（约 161 MiB），公开依赖偏 ONNX Runtime/Sherpa + Vulkan/CPU，没有当前项目完整 PyTorch CUDA 栈。
- 当前代码支持 Transformers/CUDA 和 Vulkan/GGUF 两条后端；模型设计为首次下载、外置并缓存。

我在考虑：
1) 默认发布 Vulkan/GGUF，CUDA/Transformers 做单独大型包；
2) 发布小 Bootstrapper，首次按 GPU 下载对应 runtime、FFmpeg 和模型；
3) Vulkan-only，并要求系统 FFmpeg 或提供更小的定制 FFmpeg。

请：
- 先区分源码仓库、开发目录、Artifact 外层归档、解压后安装目录四种大小；
- 对上述三种方案按首包下载、安装后体积、GPU 覆盖、离线能力、首次联网、更新/回滚、安全校验、维护成本、用户体验做决策表；
- 明确指出静态 FFmpeg 约 424 MiB 的体积下限，以及“onefile”不会减少总运行时；
- 不要把 2.1 GiB 直接解释成误上传模型，也不要在没有完整解包证据时断言 Artifact 内容；
- 给出一个推荐方案和一个备选方案，说明需要我确认的产品决策；
- 最后给出分阶段实施计划：先测量 Artifact 内容，再改 packaging/workflow，再做干净 Windows 11 普通权限 EXE 验收；未验收通过前不创建 tag/Release。
```

## 8. 后续实施与验收闸门

### 阶段 0：只测量，不改代码

- 在全新目录完整下载 Artifact；不要续用不完整临时文件作为验收输入。
- 计算外层 ZIP SHA-256，并与 GitHub 记录的 digest `7d15a932ce2ae5d7ba6f790f58c7968efefd8d39994b2b72776bdcbb9e184391` 比对。
- 解压到全新、干净目录；清点分卷、7z、EXE、DLL、FFmpeg、worker、文档和是否出现模型/开发环境文件。
- 记录压缩包大小、解压后大小和各一级目录占用。此阶段只能报告事实，不能因体积问题立即改代码或打 tag。

### 阶段 1：确认架构

- 用户确认默认后端、FFmpeg、联网/离线、包数量和体积目标。
- 选择方案 A/B/C，并把不支持的 GPU、驱动和网络情形写进发布说明。

### 阶段 2：最小 packaging/workflow 改动

- 只改 spec、依赖安装、构建矩阵和发布脚本需要的部分；不重构转写逻辑。
- 每个 SKU 使用独立、可复现的依赖锁定和产物名称。
- 运行现有测试，再增加针对包清单、路径隔离、运行时选择和下载校验的测试。

### 阶段 3：真实验收

每个候选包都必须在不是开发目录的干净 Windows 11 x64 环境中：

- 普通权限启动 EXE，GUI 正常显示；
- FFmpeg/FFprobe 真实调用成功；
- Vulkan/GPU 检测、设备 ID 和后端选择正确；
- 模型发现、下载、校验、加载和缓存逻辑正常；
- 使用一个真实音频完成一次转写；
- 不依赖开发目录、本机 Python、PATH 中偶然存在的工具或未打包资源；
- 记录错误日志、启动时间、首次下载和断网后的行为。

### 阶段 4：发布

只有当 Artifact 完整、SHA-256 一致、解压结构完整、EXE 真机验收全部通过，并且用户明确确认后，才创建/推送 `v1.0.0`。在此之前不创建 tag，不发布 Release，不 force push。

## 9. 当前交接边界

- 用户指定的发布验收基线：`c1aca48`；本轮文档更新不改变源码和 workflow。
- 当前记录时 HEAD：`9e1734f`；它包含后续 CI/文档提交。不要为了“对齐”而 reset 或重写历史。
- Artifact：run `33216786493` / ID `9704253084`，尚未完成本地完整下载和验收。
- 当前未授权：任何代码改动、无关清理、新 commit、push、tag、Release、force push。
- 如果 Azure/GitHub 下载很慢，允许用户手动把完整文件放到新的干净目录；下载链路问题不是跳过验收或修改代码的理由。

## 10. 实施状态（2026-08-29）

本文件前文的“只讨论、不得改代码/commit”是当时的阶段性限制，已被后续明确授权覆盖。当前实现采用方案 A：默认 `QwenScribe-Vulkan-Windows-x64`，可选 `QwenScribe-CUDA-Windows-x64`；模型继续外置。Vulkan 本地 onedir 实测解压 653.81 MiB、标准 ZIP 253.97 MiB，FFmpeg/FFprobe 保持内置，因为已达到压缩 Artifact `<500 MiB` 硬目标及 `<300 MiB` 理想目标。

实现包含：依赖拆分、参数化 PyInstaller spec、固定 build variant、SKU 边界扫描、package size report、artifact manifest，以及独立 Windows CI SKU job。上述数字不代表干净机/真实 GPU/真实模型转写验收；这些仍需按第 8 节人工执行。
