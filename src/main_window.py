"""Dark, queue-oriented PySide6 interface for local transcription."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QMetaObject, QObject, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .config_service import ConfigService
from .build_config import current_build
from .i18n import (
    STATIC_EN,
    UI_LANGUAGES,
    asr_language_text,
    normalize_ui_language,
    queue_status_text,
    runtime_text,
    static_text,
)
from .language_map import LANGUAGE_MAP, language_for_label, valid_label_or_default
from .model_service import ModelService
from .model_download_service import (
    ModelDownloadCancelled,
    ModelDownloadService,
)
from .queue_model import QueueEntry, QueueStatus, TranscriptionQueue, format_file_size
from .styles import DARK_STYLESHEET
from .transcription_worker import TranscriptionTask, TranscriptionWorker
from .utils import is_process_elevated


LOGGER = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".webm",
    ".m4v",
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
}
FILE_FILTER = (
    "媒体文件 (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.flac "
    "*.m4a *.aac *.ogg);;所有文件 (*.*)"
)
STATUS_TEXT = {
    QueueStatus.PENDING: "等待中",
    QueueStatus.PROCESSING: "处理中",
    QueueStatus.COMPLETED: "已完成",
    QueueStatus.ERROR: "错误",
    QueueStatus.CANCELLED: "已取消",
}
STATUS_COLORS = {
    QueueStatus.PENDING: QColor("#aeb4c0"),
    QueueStatus.PROCESSING: QColor("#60a5fa"),
    QueueStatus.COMPLETED: QColor("#4ade80"),
    QueueStatus.ERROR: QColor("#f87171"),
    QueueStatus.CANCELLED: QColor("#fbbf24"),
}


def _supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


class ModelDownloadWorker(QObject):
    # Python objects are intentional: the Transformers checkpoint exceeds the
    # signed 32-bit range used by Qt's C++ ``int`` signal type.
    progress = Signal(object, object, str)
    completed = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, backend: str, region: str) -> None:
        super().__init__()
        self.backend = backend
        self.region = region
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            path = ModelDownloadService().download(
                self.backend,  # type: ignore[arg-type]
                self.region,  # type: ignore[arg-type]
                self.cancel_event,
                lambda current, total, name: self.progress.emit(current, total, name),
            )
        except ModelDownloadCancelled:
            self.cancelled.emit()
        except Exception as error:
            LOGGER.exception("模型下载失败")
            self.failed.emit(str(error))
        else:
            self.completed.emit(str(path))

    def request_cancel(self) -> None:
        self.cancel_event.set()


class DropArea(QFrame):
    paths_dropped = Signal(object)
    browse_files_requested = Signal()
    browse_folder_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropArea")
        self.setProperty("dragActive", False)
        self.setMinimumHeight(300)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        title = QLabel("将视频或音频拖到这里")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 19px; font-weight: 650;")
        subtitle = QLabel("支持单个或多个文件；全部任务在本地按顺序处理")
        subtitle.setObjectName("muted")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        buttons = QHBoxLayout()
        choose_files = QPushButton("选择文件")
        choose_folder = QPushButton("选择文件夹")
        choose_files.clicked.connect(self.browse_files_requested)
        choose_folder.clicked.connect(self.browse_folder_requested)
        buttons.addWidget(choose_files)
        buttons.addWidget(choose_folder)

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addLayout(buttons)
        layout.addStretch(1)

    def _set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            self._set_drag_active(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: object) -> None:  # noqa: N802
        self._set_drag_active(False)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._set_drag_active(False)
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()


class QueueTree(QTreeWidget):
    paths_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event: object) -> None:  # noqa: N802
        event.acceptProposedAction()  # type: ignore[attr-defined]

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    start_requested = Signal(object)
    gpu_probe_requested = Signal()
    device_discovery_requested = Signal()

    def __init__(
        self,
        config_service: ConfigService | None = None,
        model_service: Any | None = None,
        active_backend: str = "transformers",
        cuda_devices: list[tuple[str, str]] | None = None,
        vulkan_devices: list[tuple[str, str]] | None = None,
        supported_backends: frozenset[str] | None = None,
        unsupported_backend_message: str | None = None,
    ) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self._config = config_service or ConfigService()
        self._ui_language = normalize_ui_language(self._config.get("ui_language"))
        self._static_text_widgets: list[tuple[QWidget, str]] = []
        self._placeholder_widgets: list[tuple[QWidget, str]] = []
        self._queue = TranscriptionQueue()
        self._model_service = model_service
        self._tree_items: list[QTreeWidgetItem] = []
        self._task_active = False
        self._backend_available = False
        self._active_backend = active_backend
        self._supported_backends = supported_backends or current_build().backends
        self._unsupported_backend_message = unsupported_backend_message
        self._cuda_devices = list(cuda_devices or [])
        self._vulkan_devices = list(vulkan_devices or [])
        self._device_discovery_complete = bool(cuda_devices or vulkan_devices)
        if active_backend == "vulkan":
            self._active_device_id = str(getattr(model_service, "device_id", "auto"))
        else:
            self._active_device_id = f"cuda:{int(getattr(model_service, 'device_index', 0))}"
        self._stop_batch = False
        self._closing_after_cancel = False
        self._batch_indices: list[int] = []
        self._batch_position = -1
        self._current_index: int | None = None
        self._last_output_path: Path | None = None
        self._download_active = False
        self._download_thread: QThread | None = None
        self._download_worker: ModelDownloadWorker | None = None
        self._download_dialog: QProgressDialog | None = None

        self.setWindowTitle("QwenScribe Desktop")
        self.setMinimumSize(980, 700)
        self.resize(1180, 820)
        self.setStyleSheet(DARK_STYLESHEET)
        self._build_ui()
        self._capture_static_translations()
        self._restore_settings()
        self._connect_ui()
        self._start_worker_thread(model_service)
        if self._unsupported_backend_message:
            QTimer.singleShot(0, self._show_unsupported_backend_message)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(225)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 22, 18, 18)
        sidebar_layout.setSpacing(14)
        app_title = QLabel("QwenScribe")
        app_title.setObjectName("appTitle")
        app_subtitle = QLabel("Local Desktop")
        app_subtitle.setObjectName("muted")
        local_badge = QLabel("● 完全本地 · 不上传")
        local_badge.setStyleSheet("color: #4ade80; font-weight: 600;")
        sidebar_layout.addWidget(app_title)
        sidebar_layout.addWidget(app_subtitle)
        sidebar_layout.addSpacing(12)
        sidebar_layout.addWidget(local_badge)

        language_row = QHBoxLayout()
        language_row.addWidget(QLabel("界面语言"))
        self.ui_language_combo = QComboBox()
        for label, code in UI_LANGUAGES:
            self.ui_language_combo.addItem(label, code)
        language_row.addWidget(self.ui_language_combo, 1)
        sidebar_layout.addLayout(language_row)

        self.gpu_label = QLabel("正在后台检测所选推理设备…")
        self.gpu_label.setObjectName("statusCard")
        self.gpu_label.setWordWrap(True)
        self.gpu_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.queue_stats_label = QLabel("队列为空")
        self.queue_stats_label.setObjectName("statusCard")
        self.queue_stats_label.setWordWrap(True)
        sidebar_layout.addWidget(QLabel("设备"))
        sidebar_layout.addWidget(self.gpu_label)
        if is_process_elevated():
            drag_warning = QLabel(
                "当前以管理员权限运行。Windows 会阻止从普通资源管理器拖放文件；"
                "请关闭后双击 run.bat 普通启动，或使用“添加文件”。"
            )
            drag_warning.setWordWrap(True)
            drag_warning.setStyleSheet("color: #fbbf24;")
            sidebar_layout.addWidget(drag_warning)
        sidebar_layout.addWidget(QLabel("任务"))
        sidebar_layout.addWidget(self.queue_stats_label)
        sidebar_layout.addStretch(1)
        privacy = QLabel("模型在独立后台进程中驻留，多个文件顺序复用同一模型。")
        privacy.setObjectName("muted")
        privacy.setWordWrap(True)
        sidebar_layout.addWidget(privacy)
        root.addWidget(sidebar)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        title = QLabel("本地视频 / 音频转文字")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("Qwen3-ASR-1.7B · UTF-8 TXT · 无时间戳 · 单 GPU 顺序处理")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.content_stack = QStackedWidget()
        self.drop_area = DropArea()
        self.content_stack.addWidget(self.drop_area)
        self.content_stack.addWidget(self._build_queue_page())
        layout.addWidget(self.content_stack, 1)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("输出目录"))
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("选择 TXT 输出目录")
        self.select_output_button = QPushButton("选择目录")
        settings_row.addWidget(self.output_edit, 3)
        settings_row.addWidget(self.select_output_button)
        settings_row.addSpacing(12)
        settings_row.addWidget(QLabel("语言"))
        self.language_combo = QComboBox()
        for label in LANGUAGE_MAP:
            self.language_combo.addItem(label, label)
        self.language_combo.setMinimumWidth(150)
        settings_row.addWidget(self.language_combo)
        layout.addLayout(settings_row)

        compute_row = QHBoxLayout()
        compute_row.addWidget(QLabel("推理方式"))
        self.backend_combo = QComboBox()
        if "transformers" in self._supported_backends:
            self.backend_combo.addItem("官方 Transformers（PyTorch CUDA）", "transformers")
        if "vulkan" in self._supported_backends:
            self.backend_combo.addItem("transcribe.cpp（Vulkan GGUF）", "vulkan")
        compute_row.addWidget(self.backend_combo, 2)
        compute_row.addWidget(QLabel("模型"))
        self.model_combo = QComboBox()
        if "transformers" in self._supported_backends:
            self.model_combo.addItem("Qwen3-ASR-1.7B 官方 BF16/FP16", "transformers")
        if "vulkan" in self._supported_backends:
            self.model_combo.addItem("Qwen3-ASR-1.7B Q6_K GGUF", "vulkan")
        compute_row.addWidget(self.model_combo, 2)
        compute_row.addWidget(QLabel("GPU"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(280)
        compute_row.addWidget(self.device_combo, 3)
        layout.addLayout(compute_row)

        actions = QHBoxLayout()
        self.start_button = QPushButton("开始转写队列")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setMinimumHeight(40)
        self.start_button.setEnabled(False)
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.setEnabled(False)
        self.open_output_button = QPushButton("打开输出目录")
        self.open_output_button.setMinimumHeight(40)
        self.open_output_button.setEnabled(False)
        actions.addWidget(self.start_button, 2)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.open_output_button)
        layout.addLayout(actions)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(250)
        self.log_view.setMaximumHeight(115)
        self.log_view.setPlaceholderText("主要运行状态会显示在这里；完整异常写入用户日志文件。")
        layout.addWidget(self.log_view)
        root.addWidget(content, 1)

    def _build_queue_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        toolbar = QHBoxLayout()
        self.add_files_button = QPushButton("+ 添加文件")
        self.add_folder_button = QPushButton("+ 添加文件夹")
        self.remove_button = QPushButton("移除选中")
        self.clear_button = QPushButton("清空队列")
        toolbar.addWidget(self.add_files_button)
        toolbar.addWidget(self.add_folder_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.remove_button)
        toolbar.addWidget(self.clear_button)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.queue_tree = QueueTree()
        self.queue_tree.setHeaderLabels(["文件", "状态", "大小", "进度"])
        self.queue_tree.setRootIsDecorated(False)
        self.queue_tree.setAlternatingRowColors(True)
        self.queue_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.queue_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
        self.queue_tree.setColumnWidth(1, 95)
        self.queue_tree.setColumnWidth(2, 95)
        self.queue_tree.setColumnWidth(3, 80)

        preview_frame = QFrame()
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 8, 0, 0)
        preview_header = QHBoxLayout()
        preview_header.addWidget(QLabel("结果预览"))
        self.selected_path_label = QLabel("")
        self.selected_path_label.setObjectName("muted")
        self.selected_path_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.selected_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        preview_header.addWidget(self.selected_path_label, 1)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("选择队列中的文件；完成或保留 partial 后可在这里预览。")
        preview_layout.addLayout(preview_header)
        preview_layout.addWidget(self.preview)
        splitter.addWidget(self.queue_tree)
        splitter.addWidget(preview_frame)
        splitter.setSizes([330, 180])
        layout.addWidget(splitter, 1)
        return page

    def _connect_ui(self) -> None:
        self.drop_area.paths_dropped.connect(self._add_input_paths)
        self.drop_area.browse_files_requested.connect(self._choose_files)
        self.drop_area.browse_folder_requested.connect(self._choose_folder)
        self.queue_tree.paths_dropped.connect(self._add_input_paths)
        self.queue_tree.currentItemChanged.connect(self._on_queue_selection_changed)
        self.add_files_button.clicked.connect(self._choose_files)
        self.add_folder_button.clicked.connect(self._choose_folder)
        self.remove_button.clicked.connect(self._remove_selected)
        self.clear_button.clicked.connect(self._clear_queue)
        self.select_output_button.clicked.connect(self._choose_output_directory)
        self.output_edit.editingFinished.connect(self._save_output_directory)
        self.language_combo.currentTextChanged.connect(self._save_language)
        self.ui_language_combo.currentIndexChanged.connect(self._on_ui_language_changed)
        self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        self.start_button.clicked.connect(self._start_batch)
        self.cancel_button.clicked.connect(self._cancel_batch)
        self.open_output_button.clicked.connect(self._open_output_directory)

    def _start_worker_thread(self, model_service: Any | None = None) -> None:
        application_directory = (
            Path(sys.executable).resolve().parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parent.parent
        )
        self._worker_thread = QThread(self)
        self._worker_thread.setObjectName("PersistentASRWorkerThread")
        # Transformers constructs a deeply nested Qwen module graph.  The
        # Windows Qt default worker stack is too small for that construction
        # after entering the normal start_task -> _execute_task call chain and
        # can terminate python312.dll with 0xC0000005 instead of raising a
        # Python exception.
        self._worker_thread.setStackSize(64 * 1024 * 1024)
        self._worker = TranscriptionWorker(
            application_directory,
            model_service=model_service,
            supported_backends=self._supported_backends,
        )
        self._worker.moveToThread(self._worker_thread)
        self.start_requested.connect(self._worker.start_task)
        self.gpu_probe_requested.connect(self._worker.detect_gpu)
        self.device_discovery_requested.connect(self._worker.discover_devices)
        self._worker.status_changed.connect(self._on_worker_status)
        self._worker.progress_changed.connect(self._on_worker_progress)
        self._worker.user_log.connect(self._append_log)
        self._worker.language_detected.connect(self._show_detected_language)
        self._worker.gpu_info_ready.connect(self._on_gpu_info)
        self._worker.devices_discovered.connect(self._on_devices_discovered)
        self._worker.task_completed.connect(self._on_task_completed)
        self._worker.task_cancelled.connect(self._on_task_cancelled)
        self._worker.task_failed.connect(self._on_task_failed)
        self._worker_thread.start()
        self.device_discovery_requested.emit()
        self.gpu_probe_requested.emit()

    def _restore_settings(self) -> None:
        ui_index = self.ui_language_combo.findData(self._ui_language)
        self.ui_language_combo.setCurrentIndex(max(0, ui_index))
        output = self._config.get("output_directory") or str(Path.home() / "Documents")
        self.output_edit.setText(str(output))
        selected_language = valid_label_or_default(self._config.get("selected_language"))
        language_index = self.language_combo.findData(selected_language)
        self.language_combo.setCurrentIndex(max(0, language_index))
        backend_index = self.backend_combo.findData(self._active_backend)
        self.backend_combo.setCurrentIndex(max(0, backend_index))
        model_index = self.model_combo.findData(self._active_backend)
        self.model_combo.setCurrentIndex(max(0, model_index))
        self._populate_device_combo(self._active_backend, self._active_device_id)
        geometry = self._config.get("window_geometry")
        if isinstance(geometry, str) and geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        self._apply_ui_language()

    def _capture_static_translations(self) -> None:
        for widget in self.findChildren(QWidget):
            if isinstance(widget, (QLabel, QPushButton)):
                text = widget.text()
                if text in STATIC_EN and widget not in (
                    self.gpu_label,
                    self.queue_stats_label,
                    self.status_label,
                ):
                    self._static_text_widgets.append((widget, text))
            if isinstance(widget, (QLineEdit, QPlainTextEdit)):
                placeholder = widget.placeholderText()
                if placeholder in STATIC_EN:
                    self._placeholder_widgets.append((widget, placeholder))

    def _apply_ui_language(self) -> None:
        for widget, chinese in self._static_text_widgets:
            widget.setText(static_text(chinese, self._ui_language))  # type: ignore[attr-defined]
        for widget, chinese in self._placeholder_widgets:
            widget.setPlaceholderText(static_text(chinese, self._ui_language))  # type: ignore[attr-defined]
        headers = ["文件", "状态", "大小", "进度"]
        english_headers = ["File", "Status", "Size", "Progress"]
        self.queue_tree.setHeaderLabels(
            english_headers if self._ui_language == "en_US" else headers
        )
        self.backend_combo.setItemText(
            0,
            self._t(
                "官方 Transformers（PyTorch CUDA）",
                "Official Transformers (PyTorch CUDA)",
            ),
        )
        self.backend_combo.setItemText(1, "transcribe.cpp (Vulkan GGUF)")
        self.model_combo.setItemText(
            0,
            self._t(
                "Qwen3-ASR-1.7B 官方 BF16/FP16",
                "Qwen3-ASR-1.7B official BF16/FP16",
            ),
        )
        self.model_combo.setItemText(1, "Qwen3-ASR-1.7B Q6_K GGUF")
        current_language = str(self.language_combo.currentData() or "自动识别")
        self.language_combo.blockSignals(True)
        for index in range(self.language_combo.count()):
            canonical = str(self.language_combo.itemData(index))
            self.language_combo.setItemText(
                index, asr_language_text(canonical, self._ui_language)
            )
        selected_index = self.language_combo.findData(current_language)
        self.language_combo.setCurrentIndex(max(0, selected_index))
        self.language_combo.blockSignals(False)
        backend = str(self.backend_combo.currentData() or self._active_backend)
        selected_device = str(self.device_combo.currentData() or self._active_device_id)
        self._populate_device_combo(backend, selected_device)
        if not self._task_active and self.progress_bar.value() == 0:
            self.status_label.setText(self._t("就绪", "Ready"))
        self._rebuild_queue()

    def _on_ui_language_changed(self, _index: int) -> None:
        self._ui_language = normalize_ui_language(self.ui_language_combo.currentData())
        self._config.set("ui_language", self._ui_language)
        self._apply_ui_language()

    def _t(self, chinese: str, english: str) -> str:
        return english if self._ui_language == "en_US" else chinese

    def _choose_files(self) -> None:
        initial = self._config.get("last_input_directory", str(Path.home()))
        selected, _ = QFileDialog.getOpenFileNames(
            self,
            self._t("选择视频或音频", "Choose video or audio"),
            str(initial),
            FILE_FILTER if self._ui_language == "zh_CN" else "Media files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.mp3 *.wav *.flac *.m4a *.aac *.ogg);;All files (*.*)",
        )
        if selected:
            self._add_input_paths([Path(path) for path in selected])

    def _choose_folder(self) -> None:
        initial = self._config.get("last_input_directory", str(Path.home()))
        selected = QFileDialog.getExistingDirectory(
            self, self._t("选择媒体文件夹", "Choose media folder"), str(initial)
        )
        if selected:
            self._add_input_paths([Path(selected)])

    def _add_input_paths(self, raw_paths: object) -> None:
        if self._task_active:
            return
        files: list[Path] = []
        directories: list[Path] = []
        for path in (Path(value) for value in list(raw_paths)):  # type: ignore[arg-type]
            if path.is_dir():
                directories.append(path)
                files.extend(candidate for candidate in path.rglob("*") if _supported_file(candidate))
            elif _supported_file(path):
                files.append(path)
        added = self._queue.add_paths(files)
        if files:
            self._config.set("last_input_directory", str(files[0].parent))
        elif directories:
            self._config.set("last_input_directory", str(directories[0]))
        if added:
            self._append_log(f"已加入 {added} 个文件；本地 GPU 将逐个处理。")
        elif raw_paths:
            self._append_log("没有发现新的受支持媒体文件。")
        self._rebuild_queue(select_last=bool(added))

    def _remove_selected(self) -> None:
        if self._task_active:
            return
        indices = sorted(
            {
                int(item.data(0, Qt.ItemDataRole.UserRole))
                for item in self.queue_tree.selectedItems()
            }
        )
        self._queue.remove_indices(indices)
        self._rebuild_queue()

    def _clear_queue(self) -> None:
        if self._task_active:
            return
        self._queue.clear()
        self.preview.clear()
        self.selected_path_label.clear()
        self._last_output_path = None
        self._rebuild_queue()
        self._refresh_open_output_button()

    def _rebuild_queue(self, *, select_last: bool = False) -> None:
        self.queue_tree.clear()
        self._tree_items.clear()
        for index, entry in enumerate(self._queue.entries):
            item = QTreeWidgetItem()
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setText(0, entry.path.name)
            item.setToolTip(0, str(entry.path))
            self.queue_tree.addTopLevelItem(item)
            self._tree_items.append(item)
            self._update_entry_row(index)
        self.content_stack.setCurrentIndex(1 if self._queue.entries else 0)
        if select_last and self._tree_items:
            self.queue_tree.setCurrentItem(self._tree_items[-1])
        self._update_queue_stats()
        self._refresh_start_button()

    def _update_entry_row(self, index: int) -> None:
        if not 0 <= index < len(self._queue.entries) or index >= len(self._tree_items):
            return
        entry = self._queue.entries[index]
        item = self._tree_items[index]
        item.setText(
            1, queue_status_text(STATUS_TEXT[entry.status], self._ui_language)
        )
        item.setText(2, format_file_size(entry.size_bytes))
        item.setText(3, f"{entry.progress}%")
        item.setForeground(1, QBrush(STATUS_COLORS[entry.status]))
        if entry.error:
            item.setToolTip(1, entry.error)

    def _update_queue_stats(self) -> None:
        total, completed, failed, cancelled = self._queue.summary()
        if total == 0:
            self.queue_stats_label.setText(self._t("队列为空", "Queue is empty"))
        else:
            self.queue_stats_label.setText(
                self._t(
                    f"文件：{total}\n完成：{completed}\n错误：{failed}\n取消：{cancelled}",
                    f"Files: {total}\nCompleted: {completed}\nErrors: {failed}\nCancelled: {cancelled}",
                )
            )

    def _on_queue_selection_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        if current is None:
            self.selected_path_label.clear()
            self.preview.clear()
            return
        index = int(current.data(0, Qt.ItemDataRole.UserRole))
        if not 0 <= index < len(self._queue.entries):
            return
        entry = self._queue.entries[index]
        self.selected_path_label.setText(str(entry.path))
        self.selected_path_label.setToolTip(str(entry.path))
        self._load_preview(entry)
        self._refresh_open_output_button()

    def _load_preview(self, entry: QueueEntry) -> None:
        if entry.result_path is not None and entry.result_path.is_file():
            try:
                with entry.result_path.open("r", encoding="utf-8", errors="replace") as handle:
                    text = handle.read(500_001)
                if len(text) > 500_000:
                    text = text[:500_000] + "\n\n[预览已截断，完整内容请打开 TXT 文件]"
                self.preview.setPlainText(text)
            except OSError as error:
                self.preview.setPlainText(f"无法读取结果：{error}")
        elif entry.error:
            self.preview.setPlainText(entry.error)
        else:
            self.preview.clear()

    def _choose_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            self._t("选择输出目录", "Choose output folder"),
            self.output_edit.text().strip() or str(Path.home()),
        )
        if selected:
            self.output_edit.setText(selected)
            self._save_output_directory()

    def _save_output_directory(self) -> None:
        value = self.output_edit.text().strip()
        if value:
            self._config.set("output_directory", value)
        self._refresh_start_button()

    def _save_language(self, label: str) -> None:
        del label
        self._config.set(
            "selected_language", str(self.language_combo.currentData() or "自动识别")
        )

    def _populate_device_combo(self, backend: str, selected_device: str = "") -> None:
        devices = self._vulkan_devices if backend == "vulkan" else self._cuda_devices
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if backend == "vulkan":
            self.device_combo.addItem(
                self._t("Vulkan：自动选择", "Vulkan: Auto select"), "auto"
            )
        for device_id, label in devices:
            self.device_combo.addItem(label, device_id)
        if selected_device and self.device_combo.findData(selected_device) < 0:
            prefix = (
                self._t("已配置但当前不可用", "Configured but unavailable")
                if self._device_discovery_complete
                else self._t("正在检测", "Detecting")
            )
            self.device_combo.addItem(
                f"{prefix}：{selected_device}", selected_device
            )
        if not devices and not selected_device:
            self.device_combo.addItem(
                self._t("未发现可用设备", "No available device found"), ""
            )
        index = self.device_combo.findData(selected_device)
        self.device_combo.setCurrentIndex(max(0, index))
        self.device_combo.blockSignals(False)

    def _on_backend_changed(self, _index: int) -> None:
        backend = str(self.backend_combo.currentData() or "transformers")
        self.model_combo.blockSignals(True)
        model_index = self.model_combo.findData(backend)
        self.model_combo.setCurrentIndex(max(0, model_index))
        self.model_combo.blockSignals(False)
        config_key = "vulkan_device_id" if backend == "vulkan" else "cuda_device_id"
        selected = str(self._config.get(config_key, ""))
        if backend == "vulkan" and not selected:
            selected = "auto"
        if backend == "transformers" and not selected:
            selected = "cuda:0"
        self._populate_device_combo(backend, selected)
        self._config.set("inference_backend", backend)
        self._mark_backend_restart_if_needed()

    def _show_unsupported_backend_message(self) -> None:
        message = self._unsupported_backend_message
        if not message:
            return
        self.status_label.setText(message)
        self._append_log(message)
        QMessageBox.warning(self, self._t("后端不可用", "Backend unavailable"), message)

    def _on_model_changed(self, _index: int) -> None:
        backend = str(self.model_combo.currentData() or "transformers")
        backend_index = self.backend_combo.findData(backend)
        if backend_index >= 0 and backend_index != self.backend_combo.currentIndex():
            self.backend_combo.setCurrentIndex(backend_index)

    def _on_device_changed(self, _index: int) -> None:
        backend = str(self.backend_combo.currentData() or "transformers")
        device_id = str(self.device_combo.currentData() or "")
        if device_id:
            key = "vulkan_device_id" if backend == "vulkan" else "cuda_device_id"
            self._config.set(key, device_id)
        self._mark_backend_restart_if_needed()

    def _mark_backend_restart_if_needed(self) -> None:
        selected_backend = str(self.backend_combo.currentData() or "transformers")
        selected_device = str(self.device_combo.currentData() or "")
        if (
            selected_backend != self._active_backend
            or selected_device != self._active_device_id
        ):
            self.status_label.setText(
                self._t(
                    "推理方式或 GPU 已更改，请重启程序后生效",
                    "Backend or GPU changed; restart the app to apply it",
                )
            )
            self._append_log(
                self._t(
                    "推理方式或 GPU 已保存；关闭并重新运行 run.bat 后生效。",
                    "Backend or GPU saved; close and run run.bat again to apply it.",
                )
            )
        self._refresh_start_button()

    def _start_batch(self) -> None:
        if not self._queue.entries or self._task_active:
            return
        if not bool(getattr(self._model_service, "model_available", True)):
            self._offer_model_download()
            return
        output_text = self.output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(
                self,
                self._t("输出目录无效", "Invalid output folder"),
                self._t("请先选择输出目录。", "Choose an output folder first."),
            )
            return
        output_directory = Path(output_text)
        try:
            output_directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.critical(
                self,
                self._t("无法创建输出目录", "Cannot create output folder"),
                str(error),
            )
            return
        self._config.update(
            {
                "output_directory": str(output_directory),
                "selected_language": str(
                    self.language_combo.currentData() or "自动识别"
                ),
            }
        )
        self._queue.reset_all()
        self._batch_indices = list(range(len(self._queue.entries)))
        self._batch_position = -1
        self._current_index = None
        self._stop_batch = False
        self._task_active = True
        self.progress_bar.setValue(0)
        self.log_view.clear()
        self._set_controls_for_task(True)
        self._rebuild_queue()
        self._append_log(
            f"队列开始，共 {len(self._batch_indices)} 个文件；任务只在本机顺序运行。"
        )
        self._start_next_task()

    def _offer_model_download(self) -> None:
        if self._download_active:
            return
        backend = str(self.backend_combo.currentData() or "transformers")
        if backend == "vulkan":
            model_text = "Qwen3-ASR-1.7B Q6_K GGUF（约 1.69 GB）"
        else:
            model_text = "Qwen3-ASR-1.7B Transformers（约 4.7 GB）"
        message = QMessageBox(self)
        message.setWindowTitle(self._t("需要下载模型", "Model download required"))
        message.setIcon(QMessageBox.Icon.Information)
        message.setText(
            self._t(
                f"本机尚未安装 {model_text}。",
                f"{model_text} is not installed on this computer.",
            )
        )
        message.setInformativeText(
            self._t(
                "请选择下载线路。中国境内建议使用国内线路；使用 VPN 时国际线路可能更慢。\n\n"
                "模型只保存在当前用户的数据目录，不会放进软件安装包。",
                "Choose a download route. Use the China route in mainland China; with a VPN, the international route may be slower.\n\n"
                "The model is stored only in the current user's data folder and is not bundled with the application.",
            )
        )
        china_button = message.addButton(
            self._t("中国境内（推荐）", "Mainland China (recommended)"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        international_button = message.addButton(
            self._t("国际 / Hugging Face", "International / Hugging Face"),
            QMessageBox.ButtonRole.ActionRole,
        )
        message.addButton(
            self._t("取消", "Cancel"), QMessageBox.ButtonRole.RejectRole
        )
        message.exec()
        clicked = message.clickedButton()
        if clicked is china_button:
            self._start_model_download(backend, "china")
        elif clicked is international_button:
            self._start_model_download(backend, "international")

    def _start_model_download(self, backend: str, region: str) -> None:
        self._download_active = True
        self._set_controls_for_task(True)
        self.cancel_button.setEnabled(False)
        dialog = QProgressDialog(
            self._t("正在准备模型下载…", "Preparing model download…"),
            self._t("取消下载", "Cancel download"),
            0,
            100,
            self,
        )
        dialog.setWindowTitle(
            self._t("下载 Qwen3-ASR 模型", "Download Qwen3-ASR model")
        )
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        worker = ModelDownloadWorker(backend, region)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_model_download_progress)
        worker.completed.connect(self._on_model_download_completed)
        worker.failed.connect(self._on_model_download_failed)
        worker.cancelled.connect(self._on_model_download_cancelled)
        for signal in (worker.completed, worker.failed, worker.cancelled):
            signal.connect(thread.quit)
        dialog.canceled.connect(worker.request_cancel)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._clear_download_thread_refs)
        thread.finished.connect(thread.deleteLater)
        self._download_dialog = dialog
        self._download_worker = worker
        self._download_thread = thread
        source = self._t("国内线路", "China route") if region == "china" else self._t("国际线路", "international route")
        self.status_label.setText(
            self._t(f"正在通过{source}下载模型", f"Downloading model via {source}")
        )
        self._append_log(
            self._t(
                f"开始通过{source}下载模型；中断后可重新点击继续。",
                f"Started model download via {source}; restart it to resume after an interruption.",
            )
        )
        dialog.show()
        thread.start()

    def _on_model_download_progress(self, current: int, total: int, name: str) -> None:
        dialog = self._download_dialog
        if dialog is None:
            return
        percent = max(0, min(100, int(current * 100 / total))) if total else 0
        dialog.setValue(percent)
        dialog.setLabelText(
            self._t("正在下载", "Downloading")
            + f" {name}\n{current / 1024**3:.2f} / {total / 1024**3:.2f} GB"
        )

    def _finish_model_download_ui(self) -> None:
        if self._download_dialog is not None:
            self._download_dialog.close()
        self._download_dialog = None
        self._download_active = False
        self._set_controls_for_task(False)

    def _clear_download_thread_refs(self) -> None:
        self._download_worker = None
        self._download_thread = None

    def _on_model_download_completed(self, path: str) -> None:
        self._finish_model_download_ui()
        self.status_label.setText(self._t("模型下载完成", "Model download completed"))
        self._append_log(
            self._t(f"模型下载并校验完成：{path}", f"Model downloaded and verified: {path}")
        )
        QTimer.singleShot(0, self._start_batch)

    def _on_model_download_failed(self, summary: str) -> None:
        self._finish_model_download_ui()
        self.status_label.setText(self._t("模型下载失败", "Model download failed"))
        self._append_log(summary)
        QMessageBox.critical(
            self,
            self._t("模型下载失败", "Model download failed"),
            self._t(
                f"{summary}\n\n正常中断留下的 .part 文件会保留，下次可以继续下载。",
                f"{summary}\n\nA .part file from a normal interruption is retained and can be resumed next time.",
            ),
        )

    def _on_model_download_cancelled(self) -> None:
        self._finish_model_download_ui()
        self.status_label.setText(self._t("模型下载已取消", "Model download cancelled"))
        self._append_log(
            self._t(
                "模型下载已取消；已下载部分会保留供下次续传。",
                "Model download cancelled; downloaded data is retained for resuming.",
            )
        )

    def _start_next_task(self) -> None:
        if self._stop_batch:
            self._finish_batch(cancelled=True)
            return
        self._batch_position += 1
        if self._batch_position >= len(self._batch_indices):
            self._finish_batch(cancelled=False)
            return
        index = self._batch_indices[self._batch_position]
        entry = self._queue.entries[index]
        if not entry.path.is_file():
            entry.status = QueueStatus.ERROR
            entry.error = f"输入文件不存在：{entry.path}"
            self._update_entry_row(index)
            QTimer.singleShot(0, self._start_next_task)
            return

        self._current_index = index
        entry.status = QueueStatus.PROCESSING
        entry.progress = 0
        self._update_entry_row(index)
        self.queue_tree.setCurrentItem(self._tree_items[index])
        self.status_label.setText(
            self._t(
                f"文件 {self._batch_position + 1}/{len(self._batch_indices)}：正在准备",
                f"File {self._batch_position + 1}/{len(self._batch_indices)}: preparing",
            )
        )
        task = TranscriptionTask(
            input_path=entry.path,
            output_directory=Path(self.output_edit.text().strip()),
            language=language_for_label(
                str(self.language_combo.currentData() or "自动识别")
            ),
        )
        self._worker.mark_task_pending()
        self.start_requested.emit(task)

    def _cancel_batch(self) -> None:
        if not self._task_active:
            return
        self._stop_batch = True
        self.cancel_button.setEnabled(False)
        self.status_label.setText(
            self._t(
                "正在取消当前文件并停止队列…",
                "Cancelling the current file and stopping the queue…",
            )
        )
        self._append_log(
            self._t(
                "已请求取消；模型推理会在当前片段完成后停止。",
                "Cancellation requested; inference will stop after the current segment.",
            )
        )
        self._worker.request_cancel()

    def _on_worker_status(self, status: str) -> None:
        prefix = ""
        if self._batch_indices and self._batch_position >= 0:
            prefix = self._t(
                f"文件 {self._batch_position + 1}/{len(self._batch_indices)} · ",
                f"File {self._batch_position + 1}/{len(self._batch_indices)} · ",
            )
        self.status_label.setText(prefix + runtime_text(status, self._ui_language))

    def _on_worker_progress(self, progress: int) -> None:
        self.progress_bar.setValue(progress)
        if self._current_index is not None:
            entry = self._queue.entries[self._current_index]
            entry.progress = progress
            self._update_entry_row(self._current_index)

    def _on_task_completed(self, output_path: str) -> None:
        if self._current_index is None:
            return
        entry = self._queue.entries[self._current_index]
        entry.status = QueueStatus.COMPLETED
        entry.progress = 100
        entry.result_path = Path(output_path)
        self._last_output_path = entry.result_path
        self._update_entry_row(self._current_index)
        self._load_preview(entry)
        self._update_queue_stats()
        self._refresh_open_output_button()
        self._append_log(f"文件完成：{entry.path.name} → {output_path}")
        self._current_index = None
        if self._closing_after_cancel:
            self._task_active = False
            self._set_controls_for_task(False)
            QTimer.singleShot(0, self.close)
        else:
            QTimer.singleShot(0, self._start_next_task)

    def _on_task_cancelled(self, partial_path: str) -> None:
        if self._current_index is not None:
            entry = self._queue.entries[self._current_index]
            entry.status = QueueStatus.CANCELLED
            entry.result_path = Path(partial_path) if partial_path else None
            self._last_output_path = entry.result_path
            self._update_entry_row(self._current_index)
            self._load_preview(entry)
        self._current_index = None
        self._update_queue_stats()
        self._task_active = False
        self._set_controls_for_task(False)
        self._refresh_open_output_button()
        if self._closing_after_cancel:
            QTimer.singleShot(0, self.close)
            return
        message = self._t("队列已停止。", "The queue has stopped.")
        if partial_path:
            message += self._t(
                f"\n当前文件的已识别内容保存在：\n{partial_path}",
                f"\nRecognized text for the current file was saved to:\n{partial_path}",
            )
        QMessageBox.information(
            self, self._t("已取消", "Cancelled"), message
        )

    def _on_task_failed(self, summary: str, partial_path: str) -> None:
        if self._current_index is not None:
            entry = self._queue.entries[self._current_index]
            entry.status = QueueStatus.ERROR
            entry.error = summary
            entry.result_path = Path(partial_path) if partial_path else None
            if entry.result_path is not None:
                self._last_output_path = entry.result_path
            self._update_entry_row(self._current_index)
            self._load_preview(entry)
            self._append_log(f"文件失败：{entry.path.name} · {summary}")
        self._current_index = None
        self._update_queue_stats()
        self._refresh_open_output_button()
        if self._closing_after_cancel:
            self._task_active = False
            self._set_controls_for_task(False)
            QTimer.singleShot(0, self.close)
        elif self._stop_batch:
            self._finish_batch(cancelled=True)
        elif any(
            marker in summary
            for marker in (
                "找不到 ffmpeg",
                "找不到 ffprobe",
                "CUDA 不可用",
                "模型加载失败",
                "Vulkan 模型加载失败",
                "Vulkan worker",
            )
        ):
            self._task_active = False
            self._stop_batch = True
            self._set_controls_for_task(False)
            self.status_label.setText(
                self._t(
                    "队列因环境或模型错误停止",
                    "Queue stopped because of an environment or model error",
                )
            )
            QMessageBox.critical(
                self, self._t("队列已停止", "Queue stopped"), summary
            )
        else:
            QTimer.singleShot(0, self._start_next_task)

    def _finish_batch(self, *, cancelled: bool) -> None:
        if not self._task_active:
            return
        self._task_active = False
        self._current_index = None
        self._set_controls_for_task(False)
        self._update_queue_stats()
        total, completed, failed, cancelled_count = self._queue.summary()
        if cancelled:
            self.status_label.setText(self._t("队列已停止", "Queue stopped"))
        else:
            self.progress_bar.setValue(100)
            self.status_label.setText(
                self._t("队列处理完成", "Queue completed")
            )
            QMessageBox.information(
                self,
                self._t("队列完成", "Queue completed"),
                self._t(
                    f"共 {total} 个文件\n成功：{completed}\n失败：{failed}\n取消：{cancelled_count}",
                    f"Files: {total}\nSucceeded: {completed}\nFailed: {failed}\nCancelled: {cancelled_count}",
                ),
            )

    def _set_controls_for_task(self, active: bool) -> None:
        for widget in (
            self.add_files_button,
            self.add_folder_button,
            self.remove_button,
            self.clear_button,
            self.select_output_button,
            self.output_edit,
            self.language_combo,
            self.backend_combo,
            self.model_combo,
            self.device_combo,
            self.drop_area,
        ):
            widget.setEnabled(not active)
        self.cancel_button.setEnabled(active)
        self._refresh_start_button()

    def _refresh_start_button(self) -> None:
        self.start_button.setEnabled(
            bool(
                not self._task_active
                and self._backend_available
                and str(self.backend_combo.currentData() or "") == self._active_backend
                and str(self.device_combo.currentData() or "") == self._active_device_id
                and self._queue.entries
                and self.output_edit.text().strip()
            )
        )

    def _on_gpu_info(self, available: bool, description: str) -> None:
        self._backend_available = available
        self.gpu_label.setText(description)
        self.gpu_label.setStyleSheet("color: #4ade80;" if available else "color: #f87171;")
        if not available:
            self.status_label.setText(
                self._t(
                    "所选推理设备不可用",
                    "The selected inference device is unavailable",
                )
            )
            self._append_log(description)
        self._refresh_start_button()

    def _on_devices_discovered(
        self,
        cuda_devices: object,
        vulkan_devices: object,
    ) -> None:
        self._cuda_devices = list(cuda_devices)  # type: ignore[arg-type]
        self._vulkan_devices = list(vulkan_devices)  # type: ignore[arg-type]
        self._device_discovery_complete = True
        backend = str(self.backend_combo.currentData() or "transformers")
        selected = str(self.device_combo.currentData() or self._active_device_id)
        self._populate_device_combo(backend, selected)
        self._append_log(
            f"设备检测完成：CUDA {len(self._cuda_devices)} 个，"
            f"Vulkan {len(self._vulkan_devices)} 个。"
        )
        self._refresh_start_button()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self._add_input_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _show_detected_language(self, language: str) -> None:
        if self.language_combo.currentData() == "自动识别":
            self.statusBar().showMessage(
                self._t(
                    f"当前片段检测语言：{language}",
                    f"Detected language for current segment: {language}",
                ),
                7000,
            )

    def _append_log(self, message: str) -> None:
        self.log_view.appendPlainText(runtime_text(message, self._ui_language))

    def _refresh_open_output_button(self) -> None:
        selected = self.queue_tree.currentItem()
        selected_has_result = False
        if selected is not None:
            index = int(selected.data(0, Qt.ItemDataRole.UserRole))
            selected_has_result = bool(
                0 <= index < len(self._queue.entries)
                and self._queue.entries[index].result_path is not None
            )
        self.open_output_button.setEnabled(bool(selected_has_result or self._last_output_path))

    def _open_output_directory(self) -> None:
        directory: Path | None = None
        selected = self.queue_tree.currentItem()
        if selected is not None:
            index = int(selected.data(0, Qt.ItemDataRole.UserRole))
            if 0 <= index < len(self._queue.entries):
                result = self._queue.entries[index].result_path
                if result is not None:
                    directory = result.parent
        if directory is None and self._last_output_path is not None:
            directory = self._last_output_path.parent
        if directory is None:
            directory = Path(self.output_edit.text().strip())
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._download_active:
            answer = QMessageBox.question(
                self,
                self._t("模型正在下载", "Model download in progress"),
                self._t(
                    "是否取消下载？已下载部分会保留供下次续传。",
                    "Cancel the download? Downloaded data will be retained for resuming.",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes and self._download_worker is not None:
                self._download_worker.request_cancel()
                self.status_label.setText(
                    self._t("正在取消模型下载…", "Cancelling model download…")
                )
            event.ignore()
            return
        if self._task_active:
            answer = QMessageBox.question(
                self,
                self._t("任务正在运行", "Task in progress"),
                self._t(
                    "是否取消当前文件、停止队列并退出？\n已经完成的文件和 partial 文本会保留。",
                    "Cancel the current file, stop the queue, and exit?\nCompleted files and partial text will be retained.",
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing_after_cancel = True
            self._cancel_batch()
            event.ignore()
            return

        geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self._config.update(
            {
                "window_geometry": geometry,
                "output_directory": self.output_edit.text().strip(),
                "selected_language": str(
                    self.language_combo.currentData() or "自动识别"
                ),
                "ui_language": self._ui_language,
            }
        )
        QMetaObject.invokeMethod(
            self._worker,
            "shutdown_backend",
            Qt.ConnectionType.BlockingQueuedConnection,
        )
        self._worker_thread.quit()
        if not self._worker_thread.wait(5000):
            LOGGER.error("后台线程未能在 5 秒内退出")
            event.ignore()
            QMessageBox.warning(
                self,
                self._t("暂时无法退出", "Cannot exit yet"),
                self._t(
                    "后台线程仍在收尾，请稍后再次关闭。",
                    "The background thread is still finishing; try closing again shortly.",
                ),
            )
            return
        event.accept()
