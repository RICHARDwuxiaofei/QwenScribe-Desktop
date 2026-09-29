"""Small dedicated Gal Cutter panel; ordinary STT widgets remain untouched."""
from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .build_config import current_build
from .forced_aligner_service import ForcedAlignerService
from .gal_audio import inspect_wav
from .gal_alignment import CutterConfig
from .gal_cutter import CutterCancelled, run_cutter
from .gal_manifest import load_manifest
from .model_catalog import find_installed_model
from .model_service import ModelService


class GalRunWorker(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, audio: Path, manifest: Path, meta: Path | None, output: Path, qa: bool, fine_silence: bool):
        super().__init__()
        self.audio, self.manifest, self.meta, self.output, self.qa = audio, manifest, meta, output, qa
        self.cancel_event = threading.Event()
        self.aligner = ForcedAlignerService()
        self.fine_silence = fine_silence

    @Slot()
    def run(self):
        try:
            asr = ModelService() if self.qa else None
            result = run_cutter(self.audio, self.manifest, self.output, meta=self.meta, config=CutterConfig(fine_silence=self.fine_silence), aligner=self.aligner, asr_service=asr, resume=True, cancel=self.cancel_event, progress=lambda a, b, c: self.progress.emit(a, b, c))
            self.finished.emit(result)
        except CutterCancelled:
            self.failed.emit("已取消；已完成 WAV 和报告保留，可再次开始以恢复")
        except Exception as error:
            self.failed.emit("已取消；可恢复" if self.cancel_event.is_set() else str(error))
        finally:
            self.aligner.close()

    def cancel(self):
        self.cancel_event.set()
        self.aligner.cancel()


class GalCutterPage(QWidget):
    download_requested = Signal(str, str)
    running_changed = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.worker = None
        self.thread = None
        layout = QVBoxLayout(self)
        title = QLabel("Gal TTS Alignment & Cutter")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(QLabel("准确剧本文本 → Forced Aligner → 自然边界 → 每句 WAV"))
        self.edits = {}
        for key, label, select, directory in (("audio", "Master WAV", "选择 WAV", False), ("manifest", "Batch JSONL", "选择 JSONL", False), ("meta", "Metadata（可选）", "选择 JSON", False), ("output", "输出根目录", "选择目录", True)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            edit = QLineEdit()
            edit.textChanged.connect(self.refresh)
            row.addWidget(edit, 1)
            button = QPushButton(select)
            button.clicked.connect(lambda checked=False, e=edit, d=directory, k=key: self.choose(e, d, k))
            row.addWidget(button)
            layout.addLayout(row)
            self.edits[key] = edit
        self.info = QLabel("选择 WAV 与 JSONL；也可将文件拖入此页面")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        model_row = QHBoxLayout()
        self.model_status = QLabel()
        model_row.addWidget(self.model_status, 1)
        self.region = QComboBox()
        self.region.addItem("ModelScope（中国）", "china")
        self.region.addItem("Hugging Face（国际）", "international")
        model_row.addWidget(self.region)
        self.download = QPushButton("下载 Forced Aligner")
        self.download.clicked.connect(lambda: self.download_requested.emit("forced_aligner", str(self.region.currentData())))
        model_row.addWidget(self.download)
        layout.addLayout(model_row)
        self.alignment = QCheckBox("Forced Alignment（必选）")
        self.alignment.setChecked(True)
        self.alignment.setEnabled(False)
        self.silence = QCheckBox("Fine silence refinement")
        self.silence.setChecked(True)
        self.qa = QCheckBox("Qwen ASR QA（完成切割后运行）")
        for box in (self.alignment, self.silence, self.qa):
            layout.addWidget(box)
        actions = QHBoxLayout()
        self.start = QPushButton("开始切割")
        self.start.clicked.connect(self.start_run)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_run)
        actions.addWidget(self.start)
        actions.addWidget(self.cancel_button)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.results = QTreeWidget()
        self.results.setHeaderLabels(["Job", "状态", "时长", "输出"])
        self.results.currentItemChanged.connect(self.show_selection)
        self._rows = {}
        layout.addWidget(self.results, 1)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(130)
        layout.addWidget(self.preview)
        self.refresh()

    def choose(self, edit, directory: bool, key: str):
        if directory:
            value = QFileDialog.getExistingDirectory(self, "选择输出根目录")
        else:
            suffix = "WAV (*.wav)" if key == "audio" else "JSONL (*.jsonl)" if key == "manifest" else "JSON (*.json)"
            value, _ = QFileDialog.getOpenFileName(self, "选择输入", "", suffix)
        if value:
            edit.setText(value)

    def dragEnterEvent(self, event: QDragEnterEvent):  # noqa: N802
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):  # noqa: N802
        for url in event.mimeData().urls():
            if url.isLocalFile():
                path = Path(url.toLocalFile())
                if path.suffix.lower() == ".wav":
                    self.edits["audio"].setText(str(path))
                elif path.suffix.lower() == ".jsonl":
                    self.edits["manifest"].setText(str(path))
                elif path.name.endswith(".meta.json"):
                    self.edits["meta"].setText(str(path))
        event.acceptProposedAction()

    def refresh(self):
        supported = "transformers" in current_build().backends
        installed = find_installed_model("forced_aligner", Path.cwd())
        self.model_status.setText("Forced Aligner：已安装" if installed else "Forced Aligner：未安装")
        self.download.setEnabled(supported)
        self.start.setEnabled(supported and self.worker is None and bool(self.edits["audio"].text() and self.edits["manifest"].text() and self.edits["output"].text()))
        if not supported:
            self.info.setText("Gal TTS Cutter requires the CUDA / Transformers build.")
            return
        try:
            jobs = load_manifest(Path(self.edits["manifest"].text()))
            duration = inspect_wav(Path(self.edits["audio"].text()))[-1]
            self.info.setText(f"{jobs[0].character_id} · {jobs[0].language} · {len(jobs)} jobs · {duration:.1f}s")
        except Exception:
            pass

    def start_run(self):
        self.results.clear()
        self.preview.clear()
        self.worker = GalRunWorker(Path(self.edits["audio"].text()), Path(self.edits["manifest"].text()), Path(self.edits["meta"].text()) if self.edits["meta"].text() else None, Path(self.edits["output"].text()), self.qa.isChecked(), self.silence.isChecked())
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup)
        self.start.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.running_changed.emit(True)
        self.thread.start()

    def cancel_run(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)

    def on_progress(self, current: int, total: int, name: str):
        self.progress.setValue(round(current * 100 / total))
        self.info.setText(f"{current}/{total} · {name}")

    def on_finished(self, report: dict):
        self.info.setText(report["status"] + (" · 已复用输出" if report.get("resume_skipped") else ""))
        self._rows = {row["job_id"]: row for row in report["lines"]}
        for row in report["lines"]:
            QTreeWidgetItem(self.results, [row["job_id"], row["alignment_status"], f"{row['duration']:.2f}s", row["output_relpath"]])
        self.preview.setPlainText(str(Path(self.edits["output"].text()) / "alignment_report.json"))

    def show_selection(self, item, previous):
        if item is None:
            return
        row = self._rows.get(item.text(0))
        if row:
            self.preview.setPlainText(f"{row['text']}\n{row['cut_start']:.3f}s → {row['cut_end']:.3f}s\n{row['output_relpath']}\n{row['diagnostic']}")

    def on_failed(self, message: str):
        self.info.setText("失败：" + message)
        self.preview.setPlainText(message)

    def cleanup(self):
        self.worker = None
        self.thread = None
        self.cancel_button.setEnabled(False)
        self.running_changed.emit(False)
        self.refresh()
