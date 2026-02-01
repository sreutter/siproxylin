"""
About dialog for Siproxylin.

Shows version information and supported XEPs.
"""

import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QPushButton, QHBoxLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ..version import get_full_version_info


logger = logging.getLogger('siproxylin.about_dialog')


class AboutDialog(QDialog):
    """About dialog showing version and supported XEPs."""

    def __init__(self, parent=None):
        super().__init__(parent)

        version_info = get_full_version_info()

        self.setWindowTitle(f"About {version_info['app_name']}")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)

        # App name (large, bold)
        app_name_label = QLabel(version_info['app_name'])
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        app_name_label.setFont(font)
        app_name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(app_name_label)

        # Version
        version_label = QLabel(f"Version: {version_info['version']}")
        version_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(version_label)

        # Build/Codename
        codename_label = QLabel(f"Build: {version_info['codename']}")
        codename_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(codename_label)

        layout.addSpacing(20)

        # XEPs section header
        xeps_header = QLabel("Supported XEPs:")
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        xeps_header.setFont(font)
        layout.addWidget(xeps_header)

        # XEPs list (scrollable, read-only)
        self.xeps_text = QTextEdit()
        self.xeps_text.setReadOnly(True)

        # Format XEP list
        xep_lines = []
        for xep_num, xep_name in version_info['xeps']:
            xep_lines.append(f"- XEP-{xep_num}: {xep_name}")

        self.xeps_text.setPlainText('\n'.join(xep_lines))

        # Set monospace font for XEP list
        mono_font = QFont("Monospace")
        mono_font.setStyleHint(QFont.TypeWriter)
        self.xeps_text.setFont(mono_font)

        layout.addWidget(self.xeps_text)

        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

        logger.debug("About dialog created")
