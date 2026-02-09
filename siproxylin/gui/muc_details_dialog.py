"""
MUC (Multi-User Chat) details dialog for Siproxylin.

Shows room information, participants, and settings with a tabbed interface.
"""

import asyncio
import logging
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QWidget, QFormLayout, QCheckBox, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox,
    QSpinBox, QMessageBox, QTextEdit
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont

from ..core import get_account_manager
from ..utils.avatar import get_avatar_pixmap


logger = logging.getLogger('siproxylin.muc_details_dialog')


class MUCDetailsDialog(QDialog):
    """Dialog for viewing and managing MUC room details."""

    # Signal emitted when user wants to leave the room
    leave_room_requested = Signal(int, str)  # (account_id, room_jid)

    def __init__(self, account_id: int, room_jid: str, parent=None):
        super().__init__(parent)
        self.account_id = account_id
        self.room_jid = room_jid
        self.account_manager = get_account_manager()

        # Shared room info for both Info and Config tabs
        self.room_info = None

        # Auto-refresh timer for participant list
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._auto_refresh_participants)
        self.refresh_attempts = 0
        self.max_refresh_attempts = 15  # Stop after 30 seconds (15 * 2s)

        # Get room name using barrel API
        account = self.account_manager.get_account(account_id)
        room_name = room_jid
        if account:
            room_info = account.muc.get_room_info(room_jid)
            if room_info and room_info.name:
                room_name = room_info.name

        self.setWindowTitle(f"Room Details - {room_name}")
        self.setMinimumSize(700, 550)

        # Main layout
        layout = QVBoxLayout(self)

        # Tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Info tab
        self.info_tab = self._create_info_tab()
        self.tabs.addTab(self.info_tab, "Info")

        # Participants tab
        self.participants_tab = self._create_participants_tab()
        self.tabs.addTab(self.participants_tab, "Participants")

        # Settings tab
        self.settings_tab = self._create_settings_tab()
        self.tabs.addTab(self.settings_tab, "Settings")

        # Config tab (server-side room configuration - owner only)
        self.config_tab = self._create_config_tab()
        self.config_tab_index = self.tabs.addTab(self.config_tab, "Config")

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._save_settings)
        button_layout.addWidget(self.save_button)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        button_layout.addWidget(close_button)

        layout.addLayout(button_layout)

        # Load initial data
        self._load_room_info()
        self._load_participants()
        self._load_settings()
        self._load_config()

        logger.debug(f"MUC details dialog opened for {room_jid}")

    def closeEvent(self, event):
        """Clean up when dialog is closed."""
        # Stop auto-refresh timer to prevent memory leaks
        if self.refresh_timer.isActive():
            self.refresh_timer.stop()
            logger.debug("Stopped participant auto-refresh timer")
        super().closeEvent(event)

    def _create_info_tab(self):
        """Create the Info tab showing room details and features."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Avatar and basic info
        header_layout = QHBoxLayout()

        # Avatar (60x60)
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(60, 60)
        self.avatar_label.setScaledContents(False)
        header_layout.addWidget(self.avatar_label)

        # Room name and JID
        info_layout = QVBoxLayout()
        self.room_name_label = QLabel()
        self.room_name_label.setFont(QFont("", 12, QFont.Bold))
        info_layout.addWidget(self.room_name_label)

        self.room_jid_label = QLabel()
        self.room_jid_label.setStyleSheet("color: gray;")
        info_layout.addWidget(self.room_jid_label)

        # Our affiliation and role status
        self.our_status_label = QLabel()
        self.our_status_label.setStyleSheet("color: #0066cc; font-size: 10pt;")
        info_layout.addWidget(self.our_status_label)

        info_layout.addStretch()
        header_layout.addLayout(info_layout)
        header_layout.addStretch()

        layout.addLayout(header_layout)
        layout.addSpacing(15)

        # Subject/Description
        subject_group = QGroupBox("Room Subject")
        subject_layout = QVBoxLayout(subject_group)
        self.subject_label = QLabel("No subject set")
        self.subject_label.setWordWrap(True)
        subject_layout.addWidget(self.subject_label)
        layout.addWidget(subject_group)

        # Room Features (with Refresh button)
        features_group = QGroupBox("Room Features (XEP-0045)")
        features_main_layout = QVBoxLayout(features_group)

        # Refresh button at top
        refresh_button_layout = QHBoxLayout()
        refresh_button_layout.addStretch()
        self.refresh_config_button = QPushButton("🔄 Refresh Configuration")
        self.refresh_config_button.setToolTip("Manually refresh room configuration from server")
        self.refresh_config_button.clicked.connect(self._on_refresh_config)
        refresh_button_layout.addWidget(self.refresh_config_button)
        features_main_layout.addLayout(refresh_button_layout)

        # Features form
        features_layout = QFormLayout()
        features_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self.persistent_label = QLabel()
        features_layout.addRow("Persistent:", self.persistent_label)

        self.members_only_label = QLabel()
        features_layout.addRow("Members-only:", self.members_only_label)

        self.password_protected_label = QLabel()
        features_layout.addRow("Password-protected:", self.password_protected_label)

        self.public_label = QLabel()
        features_layout.addRow("Public (searchable):", self.public_label)

        self.moderated_label = QLabel()
        features_layout.addRow("Moderated:", self.moderated_label)

        self.nonanonymous_label = QLabel()
        features_layout.addRow("Non-anonymous:", self.nonanonymous_label)

        features_main_layout.addLayout(features_layout)
        layout.addWidget(features_group)

        # OMEMO Compatibility
        omemo_group = QGroupBox("OMEMO Encryption (XEP-0384)")
        omemo_layout = QVBoxLayout(omemo_group)

        self.omemo_compatible_label = QLabel()
        self.omemo_compatible_label.setFont(QFont("", 10, QFont.Bold))
        omemo_layout.addWidget(self.omemo_compatible_label)

        omemo_note = QLabel(
            "OMEMO in MUCs requires: Non-anonymous (MUST) + Members-only (SHOULD)"
        )
        omemo_note.setStyleSheet("color: gray; font-size: 9pt;")
        omemo_note.setWordWrap(True)
        omemo_layout.addWidget(omemo_note)

        layout.addWidget(omemo_group)

        layout.addStretch()
        return tab

    def _create_participants_tab(self):
        """Create the Participants tab showing room members."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        # Participant count header
        self.participant_count_label = QLabel()
        self.participant_count_label.setFont(QFont("", 10, QFont.Bold))
        layout.addWidget(self.participant_count_label)

        # Sync status notice
        self.sync_notice_label = QLabel()
        self.sync_notice_label.setStyleSheet("color: #856404; background-color: #fff3cd; padding: 8px; border-radius: 4px;")
        self.sync_notice_label.setWordWrap(True)
        self.sync_notice_label.setVisible(False)  # Hidden by default
        layout.addWidget(self.sync_notice_label)

        # Participants table
        self.participants_table = QTableWidget()
        self.participants_table.setColumnCount(4)
        self.participants_table.setHorizontalHeaderLabels([
            "Nickname", "JID", "Role", "Affiliation"
        ])

        # Configure table
        self.participants_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.participants_table.setSelectionMode(QTableWidget.SingleSelection)
        self.participants_table.setAlternatingRowColors(True)
        self.participants_table.verticalHeader().setVisible(False)

        # Column stretching
        header = self.participants_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Nickname
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # JID
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Role
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Affiliation

        layout.addWidget(self.participants_table)

        return tab

    def _create_settings_tab(self):
        """Create the Settings tab for local preferences."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Local Settings
        local_group = QGroupBox("Local Settings")
        local_layout = QFormLayout(local_group)
        local_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # Local alias
        self.alias_input = QLineEdit()
        self.alias_input.setPlaceholderText("Optional local nickname for this room")
        local_layout.addRow("Local Alias:", self.alias_input)

        # Notifications
        self.notifications_checkbox = QCheckBox("Enable notifications for this room")
        local_layout.addRow("Notifications:", self.notifications_checkbox)

        # Typing indicators
        self.typing_checkbox = QCheckBox("Send typing notifications in this room")
        local_layout.addRow("Typing indicators:", self.typing_checkbox)

        # Autojoin
        self.autojoin_checkbox = QCheckBox("Automatically join this room on connect")
        local_layout.addRow("Autojoin:", self.autojoin_checkbox)

        # Message history limit
        self.history_limit_spinbox = QSpinBox()
        self.history_limit_spinbox.setMinimum(10)
        self.history_limit_spinbox.setMaximum(1000)
        self.history_limit_spinbox.setSingleStep(10)
        self.history_limit_spinbox.setValue(100)
        self.history_limit_spinbox.setSuffix(" messages")
        local_layout.addRow("Message history limit:", self.history_limit_spinbox)

        layout.addWidget(local_group)

        # Actions
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)

        # Leave room button
        leave_button = QPushButton("Leave Room")
        leave_button.setStyleSheet("QPushButton { background-color: #d9534f; color: white; padding: 8px; }")
        leave_button.clicked.connect(self._on_leave_room)
        actions_layout.addWidget(leave_button)

        layout.addWidget(actions_group)

        layout.addStretch()
        return tab

    def _create_config_tab(self):
        """Create the Config tab for server-side room configuration (owner only)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Warning/info box at top
        self.config_info_label = QLabel()
        self.config_info_label.setWordWrap(True)
        self.config_info_label.setStyleSheet("color: #856404; background-color: #fff3cd; padding: 8px; border-radius: 4px;")
        layout.addWidget(self.config_info_label)

        # Room Configuration (XEP-0045)
        config_group = QGroupBox("Room Configuration (XEP-0045)")
        config_layout = QFormLayout(config_group)
        config_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # 1. Room name
        self.config_name_input = QLineEdit()
        self.config_name_input.setPlaceholderText("Room display name")
        config_layout.addRow("Room name:", self.config_name_input)

        # 2. Description
        self.config_description_input = QTextEdit()
        self.config_description_input.setPlaceholderText("Room description")
        self.config_description_input.setMaximumHeight(80)
        config_layout.addRow("Description:", self.config_description_input)

        # 3. Members-only
        self.config_members_only_checkbox = QCheckBox("Only members can join")
        config_layout.addRow("Members-only:", self.config_members_only_checkbox)

        # 4. Moderated
        self.config_moderated_checkbox = QCheckBox("New participants are visitors by default")
        config_layout.addRow("Moderated:", self.config_moderated_checkbox)

        # 5. Password protected
        password_layout = QHBoxLayout()
        self.config_password_checkbox = QCheckBox("Protect with password")
        password_layout.addWidget(self.config_password_checkbox)
        self.config_password_input = QLineEdit()
        self.config_password_input.setPlaceholderText("Room password")
        self.config_password_input.setEchoMode(QLineEdit.Password)
        self.config_password_input.setEnabled(False)
        password_layout.addWidget(self.config_password_input)
        # Enable password field when checkbox is checked
        self.config_password_checkbox.toggled.connect(self.config_password_input.setEnabled)
        config_layout.addRow("Password:", password_layout)

        # 6. Max participants
        self.config_max_users_input = QLineEdit()
        self.config_max_users_input.setPlaceholderText("100")
        config_layout.addRow("Max participants:", self.config_max_users_input)

        # 7. Persistent room
        self.config_persistent_checkbox = QCheckBox("Room persists when last member leaves")
        config_layout.addRow("Persistent room:", self.config_persistent_checkbox)

        # 8. Publicly searchable
        self.config_public_checkbox = QCheckBox("Room is listed in public directory")
        config_layout.addRow("Publicly searchable:", self.config_public_checkbox)

        # 9. Enable message history (MAM)
        self.config_mam_checkbox = QCheckBox("Server archives messages for history (XEP-0313, MAM)")
        config_layout.addRow("Enable message history:", self.config_mam_checkbox)

        layout.addWidget(config_group)

        # Save button for config (separate from local settings)
        save_config_layout = QHBoxLayout()
        save_config_layout.addStretch()
        self.save_config_button = QPushButton("Save Room Configuration")
        self.save_config_button.setStyleSheet("QPushButton { background-color: #0066cc; color: white; padding: 8px; }")
        self.save_config_button.clicked.connect(self._save_config)
        save_config_layout.addWidget(self.save_config_button)
        layout.addLayout(save_config_layout)

        layout.addStretch()
        return tab

    def _load_room_info(self):
        """Load and display room information using barrel API."""
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            logger.warning(f"Account {self.account_id} not found")
            return

        # Use barrel API to get room info (shared with Config tab)
        self.room_info = account.muc.get_room_info(self.room_jid)
        room_info = self.room_info

        if room_info:
            # Display room name and JID
            self.room_name_label.setText(room_info.name or self.room_jid)
            self.room_jid_label.setText(room_info.jid)

            # Display features
            # For disco fields (always available from disco#info)
            self.nonanonymous_label.setText("✅ Yes" if room_info.nonanonymous else "❌ No")
            self.members_only_label.setText("✅ Yes" if room_info.membersonly else "❌ No")

            # For config fields (only available if config_fetched is set)
            # config_fetched: None=not cached, 1=cached in memory
            has_config = room_info.config_fetched is not None

            if has_config:
                # Show real values from in-memory cache
                self.persistent_label.setText("✅ Yes" if room_info.persistent else "❌ No")
                self.password_protected_label.setText("✅ Yes" if room_info.password_protected else "❌ No")
                self.public_label.setText("✅ Yes" if room_info.public else "❌ No")
                self.moderated_label.setText("✅ Yes" if room_info.moderated else "❌ No")
            else:
                # Show unknown (config not cached)
                self.persistent_label.setText("❓ Unknown")
                self.password_protected_label.setText("❓ Unknown")
                self.public_label.setText("❓ Unknown")
                self.moderated_label.setText("❓ Unknown")

            # OMEMO compatibility
            if room_info.omemo_compatible:
                self.omemo_compatible_label.setText("✅ This room supports OMEMO encryption")
                self.omemo_compatible_label.setStyleSheet("color: green;")
            else:
                self.omemo_compatible_label.setText("⚠️ This room does NOT support OMEMO encryption")
                self.omemo_compatible_label.setStyleSheet("color: orange;")

                # Explain why
                if not room_info.nonanonymous:
                    reason = QLabel("Reason: Room is anonymous (must be non-anonymous for OMEMO)")
                    reason.setStyleSheet("color: gray; font-size: 9pt;")
                    self.omemo_compatible_label.parent().layout().addWidget(reason)
                elif not room_info.membersonly:
                    reason = QLabel("Reason: Room is open (should be members-only for OMEMO)")
                    reason.setStyleSheet("color: gray; font-size: 9pt;")
                    self.omemo_compatible_label.parent().layout().addWidget(reason)

            # Display subject/description
            if room_info.subject:
                self.subject_label.setText(room_info.subject)
            else:
                self.subject_label.setText("(Subject not yet available)")

        else:
            # No room info found - show defaults
            self.room_name_label.setText(self.room_jid)
            self.room_jid_label.setText(self.room_jid)
            self.persistent_label.setText("❓ Unknown")
            self.members_only_label.setText("❓ Unknown")
            self.password_protected_label.setText("❓ Unknown")
            self.public_label.setText("❓ Unknown")
            self.moderated_label.setText("❓ Unknown")
            self.nonanonymous_label.setText("❓ Unknown")
            self.omemo_compatible_label.setText("❓ Room features not yet discovered")
            self.omemo_compatible_label.setStyleSheet("color: gray;")
            self.subject_label.setText("(Subject not yet available)")

        # Display our affiliation and role in the room
        affiliation = account.muc.get_own_affiliation(self.room_jid)
        role = account.muc.get_own_role(self.room_jid)

        if affiliation and role:
            # Format affiliation with emoji/icon
            affiliation_icons = {
                'owner': '👑',
                'admin': '⚙️',
                'member': '👤',
                'none': '👻',
                'outcast': '🚫'
            }
            role_icons = {
                'moderator': '🛡️',
                'participant': '💬',
                'visitor': '👁️',
                'none': '🔇'
            }

            affiliation_icon = affiliation_icons.get(affiliation, '❓')
            role_icon = role_icons.get(role, '❓')

            # Capitalize first letter of affiliation/role
            affiliation_display = affiliation.capitalize()
            role_display = role.capitalize()

            self.our_status_label.setText(
                f"{affiliation_icon} {affiliation_display} · {role_icon} {role_display}"
            )
        else:
            self.our_status_label.setText("⏳ Status not yet available")

        # Update refresh button state based on ownership
        # Only owners can query room configuration (XEP-0045 §10)
        is_owner = account.muc.is_room_owner(self.room_jid)
        self.refresh_config_button.setEnabled(is_owner)

        if is_owner:
            self.refresh_config_button.setToolTip("Refresh room configuration from server (owner privilege)")
        else:
            if affiliation:
                self.refresh_config_button.setToolTip(
                    f"Only room owners can refresh configuration (you are: {affiliation})"
                )
            else:
                self.refresh_config_button.setToolTip(
                    "Only room owners can refresh configuration (not yet joined)"
                )

        # Load avatar
        try:
            avatar_pixmap = get_avatar_pixmap(
                account_id=self.account_id,
                jid=self.room_jid,
                size=60
            )
            self.avatar_label.setPixmap(avatar_pixmap)
        except Exception as e:
            logger.error(f"Failed to load avatar: {e}")

    def _load_participants(self):
        """
        Load and display room participants using barrel API.
        """
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account or not account.client:
            self.sync_notice_label.setVisible(False)
            self._show_no_participants("Not connected")
            self.refresh_timer.stop()
            return

        try:
            # Check if we've fully joined the room
            room_joined = self.room_jid in account.client.joined_rooms

            # Use barrel API to get participants
            participants = account.muc.get_participants(self.room_jid)

            if not participants:
                # Determine appropriate message based on join state
                if not room_joined:
                    message = "⏳ Joining room... Please wait."
                    self.sync_notice_label.setText(message)
                else:
                    message = "⏳ Loading participants... Presence stanzas are being received in the background."
                    self.sync_notice_label.setText(message)

                self.sync_notice_label.setVisible(True)
                self._show_no_participants("Waiting for participant list...")

                # Start auto-refresh timer if not already running
                if not self.refresh_timer.isActive():
                    self.refresh_attempts = 0
                    self.refresh_timer.start(2000)  # Check every 2 seconds

                return

            # Roster loaded successfully - stop auto-refresh timer
            self.refresh_timer.stop()
            self.sync_notice_label.setVisible(False)

        except Exception as e:
            logger.error(f"Failed to load MUC roster: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.refresh_timer.stop()
            self.sync_notice_label.setVisible(False)
            self._show_no_participants("Error loading participants")
            return

        # Update count - deduplicate by real JID if available (non-anonymous rooms)
        # Some users may have multiple nicknames (nickname changes, stale presence)
        unique_jids = set()
        anonymous_count = 0
        for p in participants:
            if p.jid:
                unique_jids.add(p.jid)
            else:
                # Anonymous room or JID not available
                anonymous_count += 1

        # Total unique participants: unique JIDs + anonymous entries
        unique_count = len(unique_jids) + anonymous_count
        self.participant_count_label.setText(f"👥 {unique_count} participant{'s' if unique_count != 1 else ''}")

        # Populate table (shows all nicknames, including duplicates for debugging)
        self.participants_table.setRowCount(len(participants))

        for row_idx, participant in enumerate(participants):
            # Nickname
            nick_item = QTableWidgetItem(participant.nick)
            nick_item.setFlags(nick_item.flags() & ~Qt.ItemIsEditable)
            self.participants_table.setItem(row_idx, 0, nick_item)

            # JID (if known - depends on room being non-anonymous)
            jid_text = participant.jid if participant.jid else "(hidden)"
            jid_item = QTableWidgetItem(jid_text)
            jid_item.setFlags(jid_item.flags() & ~Qt.ItemIsEditable)
            if not participant.jid:
                jid_item.setForeground(Qt.gray)
            self.participants_table.setItem(row_idx, 1, jid_item)

            # Role (from live presence)
            role_item = QTableWidgetItem(participant.role)
            role_item.setFlags(role_item.flags() & ~Qt.ItemIsEditable)
            self.participants_table.setItem(row_idx, 2, role_item)

            # Affiliation (from live presence)
            affiliation_item = QTableWidgetItem(participant.affiliation)
            affiliation_item.setFlags(affiliation_item.flags() & ~Qt.ItemIsEditable)
            self.participants_table.setItem(row_idx, 3, affiliation_item)

    def _show_no_participants(self, message: str):
        """
        Show message in participants table when no participants available.

        Args:
            message: Message to display
        """
        self.participant_count_label.setText("0 participants")
        self.participants_table.setRowCount(1)
        no_participants_item = QTableWidgetItem(message)
        no_participants_item.setFlags(no_participants_item.flags() & ~Qt.ItemIsEditable)
        no_participants_item.setForeground(Qt.gray)
        self.participants_table.setItem(0, 0, no_participants_item)
        self.participants_table.setSpan(0, 0, 1, 4)

    def _auto_refresh_participants(self):
        """
        Auto-refresh timer callback to reload participant list.
        Stops after max_refresh_attempts to avoid infinite polling.
        """
        self.refresh_attempts += 1

        # Stop if we've tried too many times (30 seconds)
        if self.refresh_attempts >= self.max_refresh_attempts:
            self.refresh_timer.stop()
            logger.warning(f"Auto-refresh stopped after {self.refresh_attempts} attempts")
            # Update message to indicate loading timed out
            self.sync_notice_label.setText(
                "⚠️ Participant list loading timed out. The room may have connection issues."
            )
            self.sync_notice_label.setStyleSheet("color: #721c24; background-color: #f8d7da; padding: 8px; border-radius: 4px;")
            return

        # Reload participants
        logger.debug(f"Auto-refreshing participants (attempt {self.refresh_attempts})")
        self._load_participants()

    def _load_settings(self):
        """Load local settings using barrel API."""
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            return

        # Use barrel API to get room settings
        settings = account.muc.get_room_settings(self.room_jid)
        if settings:
            self.notifications_checkbox.setChecked(settings.notification > 0)
            self.typing_checkbox.setChecked(settings.send_typing)
            self.autojoin_checkbox.setChecked(settings.autojoin)
            self.alias_input.setText(settings.local_alias)
            self.history_limit_spinbox.setValue(settings.history_limit)

    def _load_config(self):
        """Load room configuration from barrel API and populate Config tab."""
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            return

        # Check if user is room owner
        is_owner = account.muc.is_room_owner(self.room_jid)

        # Use shared room_info (already loaded by _load_room_info)
        room_info = self.room_info

        if not is_owner:
            # Non-owner: disable Config tab and show info message
            self.tabs.setTabEnabled(self.config_tab_index, False)
            affiliation = account.muc.get_own_affiliation(self.room_jid)
            affiliation_display = affiliation.capitalize() if affiliation else "Unknown"
            self.config_info_label.setText(
                f"⚠️ Only room owners can edit configuration. Your affiliation: {affiliation_display}"
            )
            # Disable all config fields
            self.config_name_input.setEnabled(False)
            self.config_description_input.setEnabled(False)
            self.config_members_only_checkbox.setEnabled(False)
            self.config_moderated_checkbox.setEnabled(False)
            self.config_password_checkbox.setEnabled(False)
            self.config_password_input.setEnabled(False)
            self.config_max_users_input.setEnabled(False)
            self.config_persistent_checkbox.setEnabled(False)
            self.config_public_checkbox.setEnabled(False)
            self.config_mam_checkbox.setEnabled(False)
            self.save_config_button.setEnabled(False)
            return

        # Owner: enable tab and load config
        self.tabs.setTabEnabled(self.config_tab_index, True)

        if not room_info or room_info.config_fetched is None:
            # Config not yet cached
            self.config_info_label.setText(
                "ℹ️ Room configuration not yet loaded. Click 'Refresh Configuration' in the Info tab first."
            )
            # Disable fields until config is loaded
            self.config_name_input.setEnabled(False)
            self.config_description_input.setEnabled(False)
            self.config_members_only_checkbox.setEnabled(False)
            self.config_moderated_checkbox.setEnabled(False)
            self.config_password_checkbox.setEnabled(False)
            self.config_password_input.setEnabled(False)
            self.config_max_users_input.setEnabled(False)
            self.config_persistent_checkbox.setEnabled(False)
            self.config_public_checkbox.setEnabled(False)
            self.config_mam_checkbox.setEnabled(False)
            self.save_config_button.setEnabled(False)
            return

        # Config loaded: populate fields
        self.config_info_label.setText(
            "✅ You are the room owner. Changes will be submitted to the server."
        )
        self.config_info_label.setStyleSheet("color: #155724; background-color: #d4edda; padding: 8px; border-radius: 4px;")

        # Populate fields from room_info
        self.config_name_input.setText(room_info.name or "")
        self.config_description_input.setText(room_info.description or "")
        self.config_members_only_checkbox.setChecked(room_info.membersonly or False)
        self.config_moderated_checkbox.setChecked(room_info.moderated or False)

        # Password: check if password_protected is True
        has_password = room_info.password_protected or False
        self.config_password_checkbox.setChecked(has_password)
        # Don't populate password field (servers typically don't return it)
        self.config_password_input.setEnabled(has_password)

        # Max users
        if room_info.max_users:
            self.config_max_users_input.setText(str(room_info.max_users))

        self.config_persistent_checkbox.setChecked(room_info.persistent or False)
        self.config_public_checkbox.setChecked(room_info.public or False)
        self.config_mam_checkbox.setChecked(room_info.enable_logging or False)

        # Enable all fields
        self.config_name_input.setEnabled(True)
        self.config_description_input.setEnabled(True)
        self.config_members_only_checkbox.setEnabled(True)
        self.config_moderated_checkbox.setEnabled(True)
        self.config_password_checkbox.setEnabled(True)
        self.config_max_users_input.setEnabled(True)
        self.config_persistent_checkbox.setEnabled(True)
        self.config_public_checkbox.setEnabled(True)
        self.config_mam_checkbox.setEnabled(True)
        self.save_config_button.setEnabled(True)

    def _save_settings(self):
        """Save local settings using barrel API."""
        try:
            # Get account
            account = self.account_manager.get_account(self.account_id)
            if not account:
                QMessageBox.warning(self, "Error", "Account not found")
                return

            # Use barrel API to update settings
            asyncio.create_task(account.muc.update_room_settings(
                room_jid=self.room_jid,
                notification=1 if self.notifications_checkbox.isChecked() else 0,
                send_typing=self.typing_checkbox.isChecked(),
                autojoin=self.autojoin_checkbox.isChecked(),
                local_alias=self.alias_input.text(),
                history_limit=self.history_limit_spinbox.value()
            ))

            logger.info(f"Saved settings for room {self.room_jid}")

            # Refresh roster to update star indicator immediately
            if self.parent() and hasattr(self.parent(), 'contact_list'):
                self.parent().contact_list.refresh()

            QMessageBox.information(self, "Settings Saved", "Room settings have been saved.")

        except Exception as e:
            logger.error(f"Failed to save settings: {e}")
            import traceback
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "Error", f"Failed to save settings: {e}")

    def _save_config(self):
        """Save room configuration to server via XEP-0004 data forms."""
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            QMessageBox.warning(self, "Error", "Account not found")
            return

        # Check ownership
        if not account.muc.is_room_owner(self.room_jid):
            QMessageBox.warning(
                self,
                "Permission Denied",
                "Only room owners can change configuration."
            )
            return

        # Validate max_users input
        max_users_text = self.config_max_users_input.text().strip()
        if max_users_text:
            try:
                max_users = int(max_users_text)
                if max_users < 0:
                    QMessageBox.warning(
                        self,
                        "Invalid Input",
                        "Max participants must be a positive number."
                    )
                    return
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid Input",
                    "Max participants must be a number."
                )
                return
        else:
            max_users = None  # Use server default

        # Collect config values from form
        config = {
            'roomname': self.config_name_input.text().strip(),
            'roomdesc': self.config_description_input.toPlainText().strip(),
            'membersonly': self.config_members_only_checkbox.isChecked(),
            'moderatedroom': self.config_moderated_checkbox.isChecked(),
            'passwordprotectedroom': self.config_password_checkbox.isChecked(),
            'roomsecret': self.config_password_input.text() if self.config_password_checkbox.isChecked() else '',
            'maxusers': max_users,
            'persistentroom': self.config_persistent_checkbox.isChecked(),
            'publicroom': self.config_public_checkbox.isChecked(),
            'enablelogging': self.config_mam_checkbox.isChecked(),
        }

        # Disable button during save
        self.save_config_button.setEnabled(False)
        self.save_config_button.setText("Saving...")

        async def do_save():
            try:
                # Submit config via barrel API
                success = await account.muc.set_room_config(self.room_jid, config)

                if success:
                    # Re-fetch full config from server to update cache
                    await account.muc.fetch_and_store_room_config(self.room_jid)

                    # Update bookmark password if changed
                    new_password = config['roomsecret']
                    if new_password or config['passwordprotectedroom']:
                        # Get JID ID
                        jid_row = account.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (self.room_jid,))
                        if jid_row:
                            jid_id = jid_row['id']
                            # Encode password (base64)
                            import base64
                            encoded_password = base64.b64encode(new_password.encode()).decode() if new_password else None
                            # Update bookmark password
                            account.db.execute(
                                "UPDATE bookmark SET password = ? WHERE account_id = ? AND jid_id = ?",
                                (encoded_password, self.account_id, jid_id)
                            )
                            account.db.commit()
                            logger.info(f"Updated bookmark password for {self.room_jid}")

                            # Sync bookmark to server (XEP-0402)
                            bookmark_row = account.db.fetchone(
                                "SELECT b.name, b.nick, b.autojoin FROM bookmark b WHERE b.account_id = ? AND b.jid_id = ?",
                                (self.account_id, jid_id)
                            )
                            if bookmark_row:
                                await account.client.add_bookmark(
                                    jid=self.room_jid,
                                    name=bookmark_row['name'] or self.room_jid,
                                    nick=bookmark_row['nick'],
                                    password=new_password,
                                    autojoin=bool(bookmark_row['autojoin'])
                                )
                                logger.debug(f"Synced bookmark password to server: {self.room_jid}")

                    # Reload both tabs from fresh server data
                    self._load_room_info()  # Updates self.room_info + Info tab
                    self._load_config()     # Config tab reads from self.room_info

                    # Non-blocking success message
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Configuration Saved")
                    msg.setText("Room configuration has been updated successfully.")
                    msg.show()

                    logger.info(f"Saved room configuration for {self.room_jid}")
                else:
                    # Non-blocking warning
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Warning)
                    msg.setWindowTitle("Save Failed")
                    msg.setText("Could not save room configuration. Please check the server logs.")
                    msg.show()

            except Exception as e:
                logger.error(f"Failed to save room config: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to save configuration:\n{e}")
                msg.show()

            finally:
                # Re-enable button
                self.save_config_button.setEnabled(True)
                self.save_config_button.setText("Save Room Configuration")

        # Run async task
        asyncio.create_task(do_save())

    def _on_refresh_config(self):
        """Manually refresh room configuration from server."""
        account = self.account_manager.get_account(self.account_id)
        if not account:
            QMessageBox.warning(self, "Error", "Account not found")
            return

        # Disable button during refresh
        self.refresh_config_button.setEnabled(False)
        self.refresh_config_button.setText("🔄 Refreshing...")

        async def do_refresh():
            try:
                # Fetch and cache room config
                success = await account.muc.fetch_and_store_room_config(self.room_jid)

                if success:
                    # Reload room info and config tabs to display updated values
                    self._load_room_info()
                    self._load_config()
                    # Non-blocking success message
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Refresh Complete")
                    msg.setText("Room configuration has been refreshed from the server.")
                    msg.show()
                else:
                    # Non-blocking warning
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Warning)
                    msg.setWindowTitle("Refresh Failed")
                    msg.setText("Could not fetch room configuration. You may not have owner permissions.")
                    msg.show()

            except Exception as e:
                logger.error(f"Failed to refresh room config: {e}")
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to refresh: {e}")
                msg.show()

            finally:
                # Re-enable button
                self.refresh_config_button.setEnabled(True)
                self.refresh_config_button.setText("🔄 Refresh Configuration")

        # Run async task
        asyncio.create_task(do_refresh())

    def _on_leave_room(self):
        """Handle Leave Room button click - emit signal for main_window to handle."""
        # Emit signal - main_window will handle the actual leaving logic
        self.leave_room_requested.emit(self.account_id, self.room_jid)

        # Close dialog (main_window will show confirmation and handle everything)
        self.accept()
