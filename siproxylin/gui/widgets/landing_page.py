"""
Landing page widget shown when no conversation is selected.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PySide6.QtCore import Qt, Signal, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
import os


class LandingPage(QWidget):
    """Landing page with brick heart illustration and action buttons."""

    # Signals
    add_account_clicked = Signal()
    create_account_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        """Setup the landing page UI."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)
        main_layout.setSpacing(30)

        # Landing page illustration (brick heart with XEPs)
        # Try PNG first (pre-converted during build), fallback to SVG
        png_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "resources", "icons", "landing.png"
        )
        svg_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "resources", "icons", "landing.svg"
        )

        # Prefer PNG for better compatibility (no Qt6Svg dependency)
        image_path = png_path if os.path.exists(png_path) else svg_path

        if os.path.exists(image_path):
            # Use QLabel + QPixmap
            image_label = QLabel()
            image_label.setAlignment(Qt.AlignCenter)

            # Load image as pixmap
            pixmap = QPixmap(image_path)
            if not pixmap.isNull():
                # Scale to 500x500 while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(
                    QSize(500, 500),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                image_label.setPixmap(scaled_pixmap)
            else:
                # Fallback if pixmap loading failed
                image_label.setText("Welcome to Siproxylin")
                font = image_label.font()
                font.setPointSize(24)
                image_label.setFont(font)

            # Center the illustration
            image_layout = QHBoxLayout()
            image_layout.addStretch()
            image_layout.addWidget(image_label)
            image_layout.addStretch()

            main_layout.addLayout(image_layout)
        else:
            # Fallback if neither PNG nor SVG found
            placeholder = QLabel("Welcome to Siproxylin")
            placeholder.setAlignment(Qt.AlignCenter)
            font = placeholder.font()
            font.setPointSize(24)
            placeholder.setFont(font)
            main_layout.addWidget(placeholder)

        # Button container
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)

        # Add Account button
        self.add_account_btn = QPushButton("Add Account")
        self.add_account_btn.setMinimumHeight(45)
        self.add_account_btn.clicked.connect(self.add_account_clicked.emit)
        button_layout.addWidget(self.add_account_btn)

        # Create Account button
        self.create_account_btn = QPushButton("Create Account")
        self.create_account_btn.setMinimumHeight(45)
        self.create_account_btn.clicked.connect(self.create_account_clicked.emit)
        button_layout.addWidget(self.create_account_btn)

        # XMPP.org link button
        self.xmpp_link_btn = QPushButton("Learn About XMPP")
        self.xmpp_link_btn.setMinimumHeight(45)
        self.xmpp_link_btn.clicked.connect(self._open_xmpp_org)
        button_layout.addWidget(self.xmpp_link_btn)

        # Center the buttons
        button_container = QHBoxLayout()
        button_container.addStretch()
        button_container.addLayout(button_layout)
        button_container.addStretch()

        main_layout.addLayout(button_container)
        main_layout.addStretch()

    def _open_xmpp_org(self):
        """Open xmpp.org in the default browser."""
        QDesktopServices.openUrl(QUrl("https://xmpp.org"))
