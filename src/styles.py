"""Application-wide dark theme."""

from __future__ import annotations


DARK_STYLESHEET = r"""
QWidget {
    background: #111214;
    color: #e7e9ee;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}
QMainWindow { background: #0d0e10; }
QFrame#sidebar {
    background: #0c0d0f;
    border-right: 1px solid #282b31;
}
QLabel#appTitle { font-size: 22px; font-weight: 700; color: #ffffff; }
QLabel#sectionTitle { font-size: 20px; font-weight: 650; color: #ffffff; }
QLabel#muted { color: #9298a5; }
QLabel#statusCard {
    background: #17191d;
    border: 1px solid #2a2e35;
    border-radius: 8px;
    padding: 10px;
}
QFrame#dropArea {
    background: #17191d;
    border: 2px dashed #4b5260;
    border-radius: 12px;
}
QFrame#dropArea[dragActive="true"] { border-color: #3b82f6; background: #172035; }
QPushButton {
    background: #202329;
    border: 1px solid #353a44;
    border-radius: 7px;
    padding: 8px 14px;
}
QPushButton:hover { background: #292d35; border-color: #4b5260; }
QPushButton:pressed { background: #181a1f; }
QPushButton:disabled { color: #666c77; background: #181a1e; border-color: #25282e; }
QPushButton#primaryButton { background: #2563eb; border-color: #3b82f6; color: white; font-weight: 600; }
QPushButton#primaryButton:hover { background: #3474f4; }
QPushButton#dangerButton { color: #fecaca; border-color: #7f1d1d; background: #321719; }
QLineEdit, QComboBox, QPlainTextEdit {
    background: #17191d;
    border: 1px solid #343842;
    border-radius: 6px;
    padding: 7px;
    selection-background-color: #2563eb;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #3b82f6; }
QComboBox::drop-down { border: none; width: 28px; }
QTreeWidget {
    background: #15171a;
    alternate-background-color: #191b20;
    border: 1px solid #2b2f36;
    border-radius: 8px;
    outline: none;
}
QTreeWidget::item { height: 34px; border-bottom: 1px solid #22252b; }
QTreeWidget::item:selected { background: #1e3a68; }
QHeaderView::section {
    background: #1d2025;
    color: #aeb4c0;
    border: none;
    border-right: 1px solid #2c3037;
    border-bottom: 1px solid #343842;
    padding: 8px;
    font-weight: 600;
}
QProgressBar {
    background: #202329;
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #3b82f6; border-radius: 5px; }
QSplitter::handle { background: #2a2d33; height: 1px; }
QScrollBar:vertical { background: #121316; width: 11px; }
QScrollBar::handle:vertical { background: #3a3e47; border-radius: 5px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""
