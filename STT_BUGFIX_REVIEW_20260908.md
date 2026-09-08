# STT bugfix review — 2026-09-08

## Scope and starting state

- Repository: `RICHARDwuxiaofei/QwenScribe-Desktop`, remote `origin` verified locally.
- Started from `f79acf826656f7b1478bb9ff0779fb6891cbac82` on `codex/reduce-windows-package-size`; clean worktree, no pre-existing edits staged or included.
- Fix branch: `fix/stt-bugfix-20260908`; no merge, tag, release, deployment or history rewrite.
- Read handoff, README, entry point, dependencies, tests, packaging/CI and the Python processing chain. No applicable AGENTS.md was found.
- This is file-based local STT, not microphone recording. There are no translation, cloud ASR, subtitle or OSC output modules to validate.
- Original baseline: 36 pytest tests passed; compileall and `app.py --check` passed. Sandbox Python launcher failure was an environment restriction, resolved by running the same existing interpreter outside the sandbox. No dependencies were upgraded.
- A full baseline package rebuild was not performed; the final Vulkan package was built locally. CUDA packaging remains covered by the repository CI rather than a local CUDA rebuild.

## Confirmed fixes and evidence

1. **Vulkan manual language selection interrupted recognition.** UI canonical names such as `English` were forwarded unchanged, but pinned transcribe-cpp 0.1.3 validates BCP-47 codes (`en`, `zh`, `yue`, etc.). `language_map.py` now adapts all 30 UI languages only at the Vulkan boundary; Transformers parameters and saved UI settings remain compatible. Reproduced `decode_failure` on both the original commit and pre-fix code with the same local synthesized sentence; automatic language succeeded. After the fix, manual English produced the complete reference sentence. Parameter regression tests first failed for English, Chinese, Cantonese and Filipino and now pass; coverage asserts every manual UI language has a mapping.
2. **Cancellation was lost at startup or reported as success on the last segment.** In `TranscriptionWorker.start_task`, the cancel event was cleared after releasing the busy lock, and no cancellation check preceded finalization. Event initialization now occurs under that lock; finalization checks cancellation after completed text has been durably appended. Deterministic regression tests first failed and now confirm cancellation, retained final-segment partial text, and clean restart with no duplicated old text.
3. **Terminal signals raced with previous-task cleanup.** Completion/failure/cancellation signals preceded cleanup, allowing the GUI to mark the next task pending before the previous task cleared those flags. Terminal signals now follow cleanup and release of busy state. A regression test verifies notification observes an idle worker and no temporary directory, and that the next task's pending cancellation remains intact.
4. **Dead backend processes still appeared loaded.** Both backend `is_loaded` properties trusted a cached flag. They now verify child liveness so the next task can enter model loading instead of sending inference to a fresh, unactivated worker. Tests simulate exited children for both implementations. Transformers also rejects a missing local model before starting a load request, avoiding its previous implicit repository-ID fallback in the production subprocess path; tested with no actual download.
5. **Vulkan heartbeats could keep a request alive indefinitely; broken transports retained stale state.** `_request` now uses a monotonic request deadline rather than resetting the full timeout for each frame. Transport errors dispose the session without recursive shutdown requests; subsequent tasks must reload. Frame reads apply the 4 MiB limit during reading instead of after an unbounded allocation. Tests reproduce deadline overrun, stale state after EOF and unbounded frame reading before the fix. Normal worker-reported errors, including OOM, still propagate without destroying a healthy session.
6. **Media exceptions could leave a child process alive.** The previous cleanup only cleared a Python reference. `MediaService` now reaps the process and closes its output pipe on all paths, and checks cancellation before launch and after publishing the child handle. A real short-lived Python helper process demonstrated the old leak when its progress consumer raised; the regression confirms the child is now gone. FFprobe nonfinite durations are rejected before they reach progress arithmetic or segment planning (NaN/Infinity regressions).

Additional regression coverage checks recursive OOM splitting covers the full 500-second interval exactly once and that real FFmpeg converts 44.1 kHz stereo synthetic silence to a 16 kHz mono PCM chunk, dispatches inference and finalizes the text file. The latter uses a model stub and proves processing logic, not recognition accuracy.

## Validation commands and results

Commands run from the repository root using the existing environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp
.\.venv\Scripts\python.exe -m compileall -q app.py src tests
.\.venv\Scripts\python.exe app.py --check
```

Final suite: **61 passed**, including the existing offscreen Qt window tests. No lint/type-check tool is configured by the project; compileall and diff checks were used without introducing a new framework.

```powershell
$env:QWENSCRIBE_BUILD_VARIANT = 'vulkan'
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --workpath build\stt-bugfix-pyinstaller --distpath dist\stt-bugfix-validation QwenASRDesktop.spec
.\scripts\report_package_size.ps1 -PackageDirectory dist\stt-bugfix-validation\QwenScribe-Vulkan-Windows-x64 -BuildVariant vulkan -OutputDirectory build\stt-bugfix-validation\size-report
git diff --check
```

Vulkan local build succeeded. Packaged `QwenScribeDesktop.exe` was launched from the parent directory with `QWENSCRIBE_RUN_CHECK=1` and an explicit `QWENSCRIBE_CHECK_OUTPUT`; it exited 0, reported `frozen=true`, only the Vulkan backend, bundled media tools/worker and `references_development_directory=false`. Package boundary reporting succeeded. This is not clean-machine acceptance.

Local diagnostic helpers and artifacts are intentionally confined to ignored `build/stt-bugfix-validation` and `dist/stt-bugfix-validation` directories. A Windows System.Speech synthesizer generated this non-sensitive reference without a network service:

> This is a local speech recognition test. The quick brown fox jumps over the lazy dog.

The local helper commands were:

```powershell
.\.venv\Scripts\python.exe build\stt-bugfix-validation\check_backends.py vulkan --baseline
.\.venv\Scripts\python.exe build\stt-bugfix-validation\check_backends.py vulkan --auto
.\.venv\Scripts\python.exe build\stt-bugfix-validation\check_backends.py vulkan
.\.venv\Scripts\python.exe build\stt-bugfix-validation\check_backends.py cuda
```

The baseline helper imported a `git archive` copy of the original `src` without changing checkout history. The final Vulkan manual-English and CUDA `cuda:0` runs both returned the full reference sentence and confirmed child exit after `close()`. Vulkan device `0000:01:00.0` was enumerated as NVIDIA GeForce RTX 4070 SUPER; Intel UHD 770 was enumerated but not used for inference. Existing local models were used, with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`. No real recordings were read or uploaded and no large models downloaded. Timings differed due to cold/warm loading and are not benchmark comparisons.

## Remaining validation boundaries

- No newly confirmed blocking defect is intentionally left in these fixes. Passing tests do not establish the absence of all bugs.
- No long-form natural speech, noisy input, non-English accuracy or GPU-memory endurance test; no Intel/AMD inference or fresh-machine package acceptance.
- CUDA cancellation still waits for the active native inference call, as designed; no unsafe kernel termination was added.
- Network download routes were inspected and existing mocked resume/checksum tests passed; real multi-GB download, connection interruption and credential scenarios were not exercised.
- Full CUDA packaging/dual-SKU GitHub Actions results must be checked separately; source tests and real local CUDA inference do not establish package acceptance.
- Manual follow-up: start `run.bat`, transcribe a short familiar recording with auto/manual language; cancel during the final segment, verify partial retention, then restart and verify text does not contain stale output. Backend/GPU changes retain the existing restart requirement.
