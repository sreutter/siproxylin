"""
Dialog for inviting contacts to a MUC room.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                                QLineEdit, QTextEdit, QPushButton)


class InviteContactDialog(QDialog):
    """Dialog for inviting a contact to a MUC room."""

    def __init__(self, parent, room_jid: str):
        """
        Initialize invite contact dialog.

        Args:
            parent: Parent widget
            room_jid: Room JID to invite to
        """
        super().__init__(parent)
        self.room_jid = room_jid
        self.invitee_jid = None
        self.reason = ""

        self.setWindowTitle("Invite Contact to Room")
        self.setModal(True)
        self.setMinimumWidth(450)

        self._setup_ui()

    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout()

        # Room info
        room_label = QLabel(f"<b>Invite to:</b> {self.room_jid}")
        layout.addWidget(room_label)

        layout.addSpacing(15)

        # JID input
        jid_label = QLabel("Contact JID:")
        layout.addWidget(jid_label)

        self.jid_input = QLineEdit()
        self.jid_input.setPlaceholderText("user@example.com")
        self.jid_input.textChanged.connect(self._on_jid_changed)
        layout.addWidget(self.jid_input)

        layout.addSpacing(10)

        # Reason field
        reason_label = QLabel("Invitation message (optional):")
        layout.addWidget(reason_label)

        self.reason_text = QTextEdit()
        self.reason_text.setPlaceholderText("Enter an optional message to include with the invitation...")
        self.reason_text.setMaximumHeight(80)
        layout.addWidget(self.reason_text)

        layout.addSpacing(10)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)

        self.invite_button = QPushButton("Send Invite")
        self.invite_button.setDefault(True)
        self.invite_button.clicked.connect(self._on_invite_clicked)
        self.invite_button.setEnabled(False)
        button_layout.addWidget(self.invite_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        # Focus JID input
        self.jid_input.setFocus()

    def _on_jid_changed(self, text):
        """Enable invite button only if JID is entered."""
        self.invite_button.setEnabled(len(text.strip()) > 0)

    def _on_invite_clicked(self):
        """Handle invite button click."""
        jid = self.jid_input.text().strip()
        if not jid:
            return

        self.invitee_jid = jid
        self.reason = self.reason_text.toPlainText().strip()
        self.accept()

    def get_invite_data(self):
        """
        Get the invite data after dialog is accepted.

        Returns:
            Tuple of (invitee_jid, reason) or None if cancelled
        """
        if self.result() == QDialog.Accepted and self.invitee_jid:
            return (self.invitee_jid, self.reason)
        return None
