"""
Dialog for selecting a MUC room and account to send invitation from.

Used in the reverse invite flow: Contact Manager -> Select Room -> Send Invite
"""

import logging
from typing import Optional, Tuple, Dict, List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QComboBox, QTextEdit, QPushButton
)
from PySide6.QtCore import Qt, QSize

from ...core import get_account_manager
from ...db.database import get_db


logger = logging.getLogger('siproxylin.select_muc_dialog')


class SelectMucDialog(QDialog):
    """Dialog for selecting MUC room and sender account for invitation."""

    def __init__(self, contact_jid: str, parent=None):
        """
        Initialize MUC selection dialog.

        Args:
            contact_jid: JID of contact to invite
            parent: Parent widget
        """
        super().__init__(parent)
        self.contact_jid = contact_jid
        self.account_manager = get_account_manager()
        self.db = get_db()

        # Result data
        self.selected_account_id = None
        self.selected_room_jid = None
        self.invitation_reason = ""

        # Room data: {room_jid: {'name': str, 'accounts': [(account_id, account_name, affiliation, role)]}}
        self.room_data = {}

        self.setWindowTitle("Invite Contact to Room")
        self.setModal(True)
        self.setMinimumWidth(550)
        self.setMinimumHeight(500)

        self._collect_room_data()
        self._setup_ui()

    def _collect_room_data(self):
        """Collect all joined MUCs across all accounts."""
        logger.debug("Collecting joined MUCs across all accounts")

        for account in self.account_manager.accounts.values():
            if not account.client or not account.client.joined_rooms:
                continue

            for room_jid in account.client.joined_rooms:
                # Get affiliation and role for this account in this room
                affiliation = account.muc.get_own_affiliation(room_jid)
                role = account.muc.get_own_role(room_jid)

                # Get account display name
                account_display = account.account_data['nickname'] or account.account_data['bare_jid']

                # Initialize room entry if not exists
                if room_jid not in self.room_data:
                    # Get room name from bookmark
                    room_name = self._get_room_name(account.account_id, room_jid)
                    self.room_data[room_jid] = {
                        'name': room_name or room_jid,
                        'accounts': []
                    }

                # Add account to this room's member list
                self.room_data[room_jid]['accounts'].append({
                    'account_id': account.account_id,
                    'account_name': account_display,
                    'affiliation': affiliation or 'none',
                    'role': role or 'none'
                })

        logger.debug(f"Found {len(self.room_data)} joined MUCs across all accounts")

    def _get_room_name(self, account_id: int, room_jid: str) -> Optional[str]:
        """Get room name from bookmark table."""
        row = self.db.fetchone("""
            SELECT b.name
            FROM bookmark b
            JOIN jid j ON b.jid_id = j.id
            WHERE b.account_id = ? AND j.bare_jid = ?
        """, (account_id, room_jid))

        return row['name'] if row and row['name'] else None

    def _setup_ui(self):
        """Setup the dialog UI."""
        layout = QVBoxLayout()

        # Contact info header
        contact_label = QLabel(f"<b>Inviting:</b> {self.contact_jid}")
        layout.addWidget(contact_label)

        layout.addSpacing(15)

        # Step 1: Select Room
        room_label = QLabel("<b>Step 1:</b> Select a room to invite them to:")
        layout.addWidget(room_label)

        self.room_list = QListWidget()
        self.room_list.setSelectionMode(QListWidget.SingleSelection)
        self.room_list.itemSelectionChanged.connect(self._on_room_selected)
        self.room_list.setSpacing(3)  # Add spacing between items
        self.room_list.setAlternatingRowColors(True)  # Better readability
        self.room_list.setMinimumHeight(200)  # Taller list (~2cm more)
        self.room_list.setStyleSheet("QListWidget { border: 2px solid palette(mid); }")  # Thicker border
        layout.addWidget(self.room_list)

        # Populate room list
        self._populate_room_list()

        # Icon legend
        legend_label = QLabel("Icons: 👑 Owner  ⚙️ Admin  🛡️ Moderator  👤 Member  💬 Participant  👁️ Visitor")
        legend_label.setStyleSheet("color: gray; font-size: 9pt;")
        layout.addWidget(legend_label)

        layout.addSpacing(15)

        # Step 2: Select Sender Account
        account_label = QLabel("<b>Step 2:</b> Send invitation from which account?")
        layout.addWidget(account_label)

        self.account_combo = QComboBox()
        self.account_combo.setEnabled(False)
        layout.addWidget(self.account_combo)

        layout.addSpacing(10)

        # Step 3: Optional Message
        message_label = QLabel("<b>Step 3:</b> Invitation message (optional):")
        layout.addWidget(message_label)

        self.reason_text = QTextEdit()
        self.reason_text.setPlaceholderText("Enter an optional message to include with the invitation...")
        self.reason_text.setMaximumHeight(80)
        layout.addWidget(self.reason_text)

        layout.addSpacing(10)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        self.invite_button = QPushButton("Send Invite")
        self.invite_button.setDefault(True)
        self.invite_button.clicked.connect(self._on_invite_clicked)
        self.invite_button.setEnabled(False)
        button_layout.addWidget(self.invite_button)

        layout.addLayout(button_layout)
        self.setLayout(layout)

    def _populate_room_list(self):
        """Populate the room list widget."""
        if not self.room_data:
            # No joined MUCs
            item = QListWidgetItem("No rooms joined. Please join a room first.")
            item.setFlags(Qt.NoItemFlags)
            self.room_list.addItem(item)
            return

        # Sort rooms by name
        sorted_rooms = sorted(self.room_data.items(), key=lambda x: x[1]['name'].lower())

        for room_jid, room_info in sorted_rooms:
            # Get highest badge emoji among all accounts in this room
            icon = self._get_highest_badge(room_info['accounts'])

            # Display format: "👑 Room Name"
            #                 "    room@conference.server.com"
            display_text = f"{icon} {room_info['name']}\n    {room_jid}"

            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, room_jid)
            item.setSizeHint(QSize(0, 50))  # Fixed height for better spacing
            self.room_list.addItem(item)

    def _get_highest_badge(self, accounts: List[Dict]) -> str:
        """
        Get the highest permission badge emoji among accounts.

        Priority: owner > admin > moderator > member > participant > visitor

        Args:
            accounts: List of account dicts with 'affiliation' and 'role'

        Returns:
            Emoji icon (e.g., '👑', '🛡️', '👤')
        """
        # Check affiliations first (higher priority)
        for account in accounts:
            if account['affiliation'] == 'owner':
                return '👑'

        for account in accounts:
            if account['affiliation'] == 'admin':
                return '⚙️'

        # Check moderator role
        for account in accounts:
            if account['role'] == 'moderator':
                return '🛡️'

        # Check member affiliation
        for account in accounts:
            if account['affiliation'] == 'member':
                return '👤'

        # Check participant role
        for account in accounts:
            if account['role'] == 'participant':
                return '💬'

        # Check visitor role
        for account in accounts:
            if account['role'] == 'visitor':
                return '👁️'

        return '❓'

    def _get_account_badge(self, affiliation: str, role: str) -> str:
        """
        Get badge emoji for a single account's affiliation/role.

        Args:
            affiliation: Account's affiliation in room
            role: Account's role in room

        Returns:
            Emoji icon
        """
        # Priority: affiliation > role
        if affiliation == 'owner':
            return '👑'
        if affiliation == 'admin':
            return '⚙️'
        if role == 'moderator':
            return '🛡️'
        if affiliation == 'member':
            return '👤'
        if role == 'participant':
            return '💬'
        if role == 'visitor':
            return '👁️'
        return '❓'

    def _on_room_selected(self):
        """Handle room selection - update account selector."""
        selected_items = self.room_list.selectedItems()
        if not selected_items:
            self.account_combo.clear()
            self.account_combo.setEnabled(False)
            self.invite_button.setEnabled(False)
            return

        # Get selected room JID
        room_jid = selected_items[0].data(Qt.UserRole)
        if not room_jid:
            return

        self.selected_room_jid = room_jid
        room_info = self.room_data[room_jid]

        # Populate account combo box with accounts that are in this room
        self.account_combo.clear()
        self.account_combo.setEnabled(True)

        # Sort accounts by permission level (highest first)
        sorted_accounts = sorted(
            room_info['accounts'],
            key=lambda a: self._get_permission_level(a['affiliation'], a['role']),
            reverse=True
        )

        for account in sorted_accounts:
            badge = self._get_account_badge(account['affiliation'], account['role'])
            display_text = f"{account['account_name']} {badge}"

            self.account_combo.addItem(display_text, account['account_id'])

        # Pre-select first account (highest permission)
        if self.account_combo.count() > 0:
            self.account_combo.setCurrentIndex(0)
            self.invite_button.setEnabled(True)

        logger.debug(f"Room selected: {room_jid}, {len(sorted_accounts)} accounts available")

    def _get_permission_level(self, affiliation: str, role: str) -> int:
        """
        Get numeric permission level for sorting.

        Returns higher number for higher permissions.
        """
        affiliation_levels = {
            'owner': 1000,
            'admin': 900,
            'member': 500,
            'none': 0,
            'outcast': -100
        }

        role_levels = {
            'moderator': 100,
            'participant': 50,
            'visitor': 10,
            'none': 0
        }

        return affiliation_levels.get(affiliation, 0) + role_levels.get(role, 0)

    def _on_invite_clicked(self):
        """Handle invite button click."""
        if not self.selected_room_jid:
            return

        # Get selected account ID from combo box
        self.selected_account_id = self.account_combo.currentData()
        if not self.selected_account_id:
            return

        # Get reason text
        self.invitation_reason = self.reason_text.toPlainText().strip()

        logger.info(f"Invite dialog: account={self.selected_account_id}, room={self.selected_room_jid}, contact={self.contact_jid}")

        self.accept()

    def get_invite_data(self) -> Optional[Tuple[int, str, str, str]]:
        """
        Get the invite data after dialog is accepted.

        Returns:
            Tuple of (account_id, room_jid, invitee_jid, reason) or None if cancelled
        """
        if self.result() == QDialog.Accepted and self.selected_account_id and self.selected_room_jid:
            return (
                self.selected_account_id,
                self.selected_room_jid,
                self.contact_jid,
                self.invitation_reason
            )
        return None
