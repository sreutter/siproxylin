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
    QSpinBox, QMessageBox, QTextEdit, QComboBox
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QColor, QBrush, QPalette

from ..core import get_account_manager
from ..utils.avatar import get_avatar_pixmap


logger = logging.getLogger('siproxylin.muc_details_dialog')


class MUCDetailsDialog(QDialog):
    """Dialog for viewing and managing MUC room details."""

    # Signals
    leave_room_requested = Signal(int, str)  # (account_id, room_jid)
    destroy_room_requested = Signal(int, str)  # (account_id, room_jid)

    def __init__(self, account_id: int, room_jid: str, parent=None):
        super().__init__(parent)
        self.account_id = account_id
        self.room_jid = room_jid
        self.account_manager = get_account_manager()

        # Dialog lifecycle flag (prevents async crashes after close)
        self._destroyed = False

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
        self.info_tab_index = self.tabs.addTab(self.info_tab, "Info")

        # Participants tab (unified: online, offline, affiliated, banned)
        self.participants_tab = self._create_participants_tab()
        self.participants_tab_index = self.tabs.addTab(self.participants_tab, "Participants")

        # Settings tab
        self.settings_tab = self._create_settings_tab()
        self.settings_tab_index = self.tabs.addTab(self.settings_tab, "Settings")

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
        self._load_config()  # This handles Config tab visibility (owner-only)
        self._update_tab_visibility()  # Handle Info/Participants visibility (joined-only)

        logger.debug(f"MUC details dialog opened for {room_jid}")

    def _update_tab_visibility(self):
        """
        Show/hide tabs based on joined status.

        Not joined (gray): Only Settings tab visible (local bookmark settings)
        Joined (blue): Info + Participants + Settings + (Config if owner)
        """
        account = self.account_manager.get_account(self.account_id)
        is_joined = (account and account.client and
                     self.room_jid in account.client.joined_rooms)

        # Info, Participants: only when joined (require disco/roster data)
        self.tabs.setTabVisible(self.info_tab_index, is_joined)
        self.tabs.setTabVisible(self.participants_tab_index, is_joined)

        # Settings: always visible (local bookmark settings)
        self.tabs.setTabVisible(self.settings_tab_index, True)

        # Config: handled separately by _load_config() (owner-only when joined)
        logger.debug(f"Tab visibility updated: is_joined={is_joined}")

    def closeEvent(self, event):
        """Clean up when dialog is closed."""
        # Mark dialog as destroyed to prevent async callbacks from accessing UI
        self._destroyed = True

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
        subject_main_layout = QVBoxLayout(subject_group)

        # Subject text
        self.subject_label = QLabel("No subject set")
        self.subject_label.setWordWrap(True)
        subject_main_layout.addWidget(self.subject_label)

        # Edit Subject button (conditional - shown only if allowed)
        subject_button_layout = QHBoxLayout()
        subject_button_layout.addStretch()
        self.edit_subject_button = QPushButton("✏️ Edit Subject")
        self.edit_subject_button.setVisible(False)  # Hidden by default
        self.edit_subject_button.clicked.connect(self._on_edit_subject)
        subject_button_layout.addWidget(self.edit_subject_button)
        subject_main_layout.addLayout(subject_button_layout)

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

        # Reason label (created dynamically when room doesn't support OMEMO)
        self.omemo_reason_label = None

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
        """Create the unified Participants tab showing all users (online, offline, affiliated, banned)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header row with count, filters, and search
        header_layout = QHBoxLayout()

        # Participant count label
        self.participant_count_label = QLabel()
        self.participant_count_label.setFont(QFont("", 10, QFont.Bold))
        header_layout.addWidget(self.participant_count_label)

        header_layout.addStretch()

        # Refresh button
        self.refresh_participants_button = QPushButton("🔄")
        self.refresh_participants_button.setToolTip("Refresh participant list")
        self.refresh_participants_button.setMaximumWidth(35)
        self.refresh_participants_button.clicked.connect(self._load_participants)
        header_layout.addWidget(self.refresh_participants_button)

        # Search box
        self.participant_search_input = QLineEdit()
        self.participant_search_input.setPlaceholderText("Search by nickname or JID...")
        self.participant_search_input.setMaximumWidth(250)
        self.participant_search_input.textChanged.connect(self._filter_participants)
        header_layout.addWidget(self.participant_search_input)

        layout.addLayout(header_layout)

        # Filter checkboxes
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Show:"))

        self.filter_online = QCheckBox("Online")
        self.filter_online.setChecked(True)
        self.filter_online.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_online)

        self.filter_offline = QCheckBox("Offline")
        self.filter_offline.setChecked(True)
        self.filter_offline.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_offline)

        filter_layout.addWidget(QLabel("|"))

        self.filter_owners = QCheckBox("Owners")
        self.filter_owners.setChecked(True)
        self.filter_owners.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_owners)

        self.filter_admins = QCheckBox("Admins")
        self.filter_admins.setChecked(True)
        self.filter_admins.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_admins)

        self.filter_members = QCheckBox("Members")
        self.filter_members.setChecked(True)
        self.filter_members.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_members)

        self.filter_outcasts = QCheckBox("Banned")
        self.filter_outcasts.setChecked(True)
        self.filter_outcasts.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_outcasts)

        self.filter_none = QCheckBox("Others")
        self.filter_none.setChecked(True)
        self.filter_none.setToolTip("Users with no affiliation")
        self.filter_none.stateChanged.connect(self._filter_participants)
        filter_layout.addWidget(self.filter_none)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # Sync/info notice
        self.sync_notice_label = QLabel()
        self.sync_notice_label.setStyleSheet("color: #856404; background-color: #fff3cd; padding: 8px; border-radius: 4px;")
        self.sync_notice_label.setWordWrap(True)
        self.sync_notice_label.setVisible(False)
        layout.addWidget(self.sync_notice_label)

        # Participants table (unified)
        self.participants_table = QTableWidget()
        self.participants_table.setColumnCount(5)
        self.participants_table.setHorizontalHeaderLabels([
            "Nickname", "JID", "Status", "Role", "Affiliation"
        ])

        # Configure table
        self.participants_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.participants_table.setSelectionMode(QTableWidget.SingleSelection)
        self.participants_table.setAlternatingRowColors(True)
        self.participants_table.verticalHeader().setVisible(False)
        self.participants_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.participants_table.customContextMenuRequested.connect(self._show_participant_context_menu)

        # Column stretching
        header = self.participants_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)  # Nickname
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # JID
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Status
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Role
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Affiliation

        layout.addWidget(self.participants_table)

        # Store all participants (online + affiliated) for filtering
        self.all_participants = []

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

        # Destroy room button (owner only, persistent rooms only)
        self.destroy_button = QPushButton("Destroy Room")
        self.destroy_button.setStyleSheet(
            "QPushButton { background-color: #a94442; color: white; padding: 8px; font-weight: bold; }"
            "QPushButton:hover { background-color: #843534; }"
        )
        self.destroy_button.setVisible(False)  # Hidden by default
        self.destroy_button.clicked.connect(self._on_destroy_room)
        actions_layout.addWidget(self.destroy_button)

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

        # Tier 2 settings (advanced)
        # 10. Allow invites
        self.config_allow_invites_checkbox = QCheckBox("Participants can invite others to the room")
        config_layout.addRow("Allow invites:", self.config_allow_invites_checkbox)

        # 11. Allow subject change
        self.config_allow_subject_change_checkbox = QCheckBox("Occupants can change the room subject/topic")
        config_layout.addRow("Allow subject change:", self.config_allow_subject_change_checkbox)

        # 12. Who can see real JIDs (whois)
        whois_layout = QVBoxLayout()
        self.config_whois_combo = QComboBox()
        self.config_whois_combo.addItem("Moderators only", "moderators")  # Default
        self.config_whois_combo.addItem("Anyone (non-anonymous)", "anyone")
        whois_layout.addWidget(self.config_whois_combo)

        # Add OMEMO note
        whois_note = QLabel("⚠️ OMEMO encryption requires 'Anyone' (non-anonymous room)")
        whois_note.setStyleSheet("color: #856404; font-size: 9pt;")
        whois_note.setWordWrap(True)
        whois_layout.addWidget(whois_note)

        config_layout.addRow("Who can see real JIDs:", whois_layout)

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

        # Only fetch live data if connected and joined
        if not account.is_connected():
            logger.debug(f"Account disconnected, showing cached data only for {self.room_jid}")
            self._load_room_info_sync()  # Load from cache/DB only
            return

        # Fetch fresh disco#info to ensure we have latest room features
        # (e.g., allow_subject_change can be changed by room owner)
        if account.client:
            async def fetch_fresh_disco():
                try:
                    logger.info(f"Fetching fresh disco#info for {self.room_jid}")
                    disco_info = await account.client.get_room_features(self.room_jid)

                    # Check if dialog was closed during async operation
                    if self._destroyed:
                        logger.debug("Dialog destroyed during disco fetch, skipping UI update")
                        return

                    # Update disco cache with fresh data
                    if not hasattr(account.client, 'disco_cache'):
                        account.client.disco_cache = {}
                    account.client.disco_cache[self.room_jid] = disco_info

                    logger.info(f"Fresh disco#info cached for {self.room_jid}")

                    # Reload room info now that we have fresh disco data
                    self._load_room_info_sync()

                except Exception as e:
                    logger.error(f"Failed to fetch fresh disco#info for {self.room_jid}: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    # Fall back to cached data
                    self._load_room_info_sync()

            # Start async fetch
            asyncio.create_task(fetch_fresh_disco())
            return

        # No client, proceed with cached data
        self._load_room_info_sync()

    def _load_room_info_sync(self):
        """Load and display room info synchronously from cache."""
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
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

                # Remove reason label if it exists (room now supports OMEMO)
                if self.omemo_reason_label:
                    self.omemo_reason_label.setParent(None)
                    self.omemo_reason_label.deleteLater()
                    self.omemo_reason_label = None
            else:
                self.omemo_compatible_label.setText("⚠️ This room does NOT support OMEMO encryption")
                self.omemo_compatible_label.setStyleSheet("color: orange;")

                # Remove old reason label if it exists
                if self.omemo_reason_label:
                    self.omemo_reason_label.setParent(None)
                    self.omemo_reason_label.deleteLater()
                    self.omemo_reason_label = None

                # Add new reason label
                reason_text = ""
                if not room_info.nonanonymous:
                    reason_text = "Reason: Room is anonymous (must be non-anonymous for OMEMO)"
                elif not room_info.membersonly:
                    reason_text = "Reason: Room is open (should be members-only for OMEMO)"

                if reason_text:
                    self.omemo_reason_label = QLabel(reason_text)
                    self.omemo_reason_label.setStyleSheet("color: gray; font-size: 9pt;")
                    self.omemo_compatible_label.parent().layout().addWidget(self.omemo_reason_label)

            # Display subject/description
            if room_info.subject:
                self.subject_label.setText(room_info.subject)
                self.subject_label.setProperty("has_subject", True)
            else:
                self.subject_label.setText("(No subject set)")
                self.subject_label.setProperty("has_subject", False)

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
            self.subject_label.setText("(No subject set)")
            self.subject_label.setProperty("has_subject", False)

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

        # Show/hide Edit Subject button based on role and room config
        # XEP-0045 §8.1 permission model:
        #   - Moderators: can ALWAYS change subject
        #   - Participants: can change IF room config allows (muc#roomconfig_changesubject)
        #   - Visitors: cannot change subject
        can_edit_subject = False

        if role == 'moderator':
            # Moderators can always change subject
            can_edit_subject = True
        elif role == 'participant' and self.room_info:
            # Participants can change if room allows (check config OR disco#info)
            # Note: allow_subject_change comes from disco#info (XEP-0128 extended room info)
            # which is available to all participants, not just owners
            can_edit_subject = self.room_info.allow_subject_change

        self.edit_subject_button.setVisible(can_edit_subject)

        # Show/hide Destroy Room button based on ownership and room persistence
        # Only owners of persistent rooms can destroy rooms (XEP-0045 §10.9)
        # Non-persistent rooms auto-delete when last occupant leaves
        is_owner = account.muc.is_room_owner(self.room_jid)
        is_persistent = room_info.persistent if (room_info and room_info.config_fetched is not None) else False
        can_destroy_room = is_owner and is_persistent

        self.destroy_button.setVisible(can_destroy_room)

        # Update refresh button state based on ownership
        # Only owners can query room configuration (XEP-0045 §10)
        is_owner = account.muc.is_room_owner(self.room_jid)
        is_admin = account.muc.is_room_admin(self.room_jid)
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
        Load and display ALL room participants (online + offline with affiliations).
        Unified view combining live presence and persistent affiliations.
        """
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account or not account.client:
            self.sync_notice_label.setVisible(False)
            self._show_no_participants("Not connected")
            self.refresh_timer.stop()
            self.refresh_participants_button.setEnabled(False)
            return

        # Disable refresh button while loading
        self.refresh_participants_button.setEnabled(False)

        # Show loading state
        self.sync_notice_label.setText("Loading participants and affiliations...")
        self.sync_notice_label.setVisible(True)

        async def fetch_unified_list():
            try:
                # 1. Fetch online participants from barrel
                online_participants = account.muc.get_participants(self.room_jid) or []

                # 2. Fetch all affiliations from server (if admin/owner)
                our_affiliation = account.muc.get_own_affiliation(self.room_jid) or 'none'
                affiliated_users = {}  # Map: JID -> affiliation

                if our_affiliation in ('owner', 'admin'):
                    try:
                        owners = await account.client.plugin['xep_0045'].get_affiliation_list(self.room_jid, 'owner')
                        admins = await account.client.plugin['xep_0045'].get_affiliation_list(self.room_jid, 'admin')
                        members = await account.client.plugin['xep_0045'].get_affiliation_list(self.room_jid, 'member')
                        outcasts = await account.client.plugin['xep_0045'].get_affiliation_list(self.room_jid, 'outcast')

                        for jid in owners:
                            affiliated_users[str(jid).lower()] = 'owner'
                        for jid in admins:
                            affiliated_users[str(jid).lower()] = 'admin'
                        for jid in members:
                            affiliated_users[str(jid).lower()] = 'member'
                        for jid in outcasts:
                            affiliated_users[str(jid).lower()] = 'outcast'
                    except Exception as e:
                        logger.warning(f"Failed to fetch affiliations (non-admin?): {e}")

                # 3. Build unified participant list
                unified_list = []
                online_jids = set()

                # Add online participants
                for p in online_participants:
                    bare_jid = p.jid.split('/')[0] if p.jid and '/' in p.jid else p.jid
                    if bare_jid:
                        bare_jid = bare_jid.lower()
                        online_jids.add(bare_jid)

                    unified_list.append({
                        'nickname': p.nick,
                        'jid': bare_jid or '(hidden)',
                        'status': 'Online',
                        'role': p.role or 'none',
                        'affiliation': p.affiliation or 'none',
                        'is_online': True
                    })

                # Add offline affiliated users (not currently online)
                for jid, affiliation in affiliated_users.items():
                    if jid not in online_jids:
                        unified_list.append({
                            'nickname': None,
                            'jid': jid,
                            'status': 'Offline',
                            'role': None,
                            'affiliation': affiliation,
                            'is_online': False
                        })

                # Store for filtering
                self.all_participants = unified_list

                # Update count label
                total_count = len(unified_list)
                online_count = len([p for p in unified_list if p['is_online']])
                self.participant_count_label.setText(
                    f"👥 {total_count} total ({online_count} online, {total_count - online_count} offline)"
                )

                # Hide loading notice
                self.sync_notice_label.setVisible(False)

                # Stop auto-refresh timer
                self.refresh_timer.stop()

                # Apply current filters
                self._filter_participants()

                logger.info(f"Loaded {total_count} participants for {self.room_jid} ({online_count} online, {total_count - online_count} offline)")

            except Exception as e:
                logger.error(f"Failed to load unified participant list: {e}")
                import traceback
                logger.error(traceback.format_exc())
                self.sync_notice_label.setText(f"⚠️ Error loading: {e}")
                self.sync_notice_label.setStyleSheet("color: #721c24; background-color: #f8d7da; padding: 8px; border-radius: 4px;")
                self._show_no_participants("Error loading participants")
            finally:
                self.refresh_participants_button.setEnabled(True)

        asyncio.create_task(fetch_unified_list())

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

    def _participant_matches_search(self, participant: dict, search_text: str) -> bool:
        """Check if participant matches search text."""
        # Search in nickname (if online)
        if participant.get('nickname') and search_text in participant['nickname'].lower():
            return True
        # Search in JID
        if participant.get('jid') and search_text in participant['jid'].lower():
            return True
        return False

    def _participant_matches_filters(self, participant: dict) -> bool:
        """Check if participant matches checkbox filters."""
        # Online/Offline filter
        if participant['is_online'] and not self.filter_online.isChecked():
            return False
        if not participant['is_online'] and not self.filter_offline.isChecked():
            return False

        # Affiliation filters
        affiliation = participant.get('affiliation', 'none')
        if affiliation == 'owner' and not self.filter_owners.isChecked():
            return False
        if affiliation == 'admin' and not self.filter_admins.isChecked():
            return False
        if affiliation == 'member' and not self.filter_members.isChecked():
            return False
        if affiliation == 'outcast' and not self.filter_outcasts.isChecked():
            return False
        if affiliation == 'none' and not self.filter_none.isChecked():
            return False

        return True

    def _get_self_highlight_color(self) -> QBrush:
        """
        Get theme-aware background color for highlighting own entry in participant list.

        Returns a subtle green tint that adapts to the current theme by blending
        with the table's base color.
        """
        # Get the table's base background color from its palette
        base_color = self.participants_table.palette().color(QPalette.Base)

        # Create a green tint
        green_tint = QColor(76, 175, 80)  # Material green-ish (#4CAF50)

        # Blend: 90% base color + 10% green tint (very subtle)
        result = QColor(
            int(base_color.red() * 0.90 + green_tint.red() * 0.10),
            int(base_color.green() * 0.90 + green_tint.green() * 0.10),
            int(base_color.blue() * 0.90 + green_tint.blue() * 0.10)
        )

        return QBrush(result)

    def _filter_participants(self, search_text=None):
        """Filter participants table based on search text and checkbox filters."""
        # Handle both checkbox state changes (int) and text changes (str)
        if isinstance(search_text, int) or search_text is None:
            search_text = self.participant_search_input.text()

        search_text = search_text.strip().lower()

        # Get total count
        total_count = len(self.all_participants)
        if total_count == 0:
            return  # No data yet

        # Filter participants by checkboxes and search
        filtered_participants = []
        for p in self.all_participants:
            # Apply checkbox filters
            if not self._participant_matches_filters(p):
                continue
            # Apply search filter
            if search_text and not self._participant_matches_search(p, search_text):
                continue
            filtered_participants.append(p)

        # Update count label
        online_count = len([p for p in filtered_participants if p['is_online']])
        offline_count = len(filtered_participants) - online_count

        if search_text or len(filtered_participants) != total_count:
            self.participant_count_label.setText(
                f"👥 {len(filtered_participants)} of {total_count} ({online_count} online, {offline_count} offline)"
            )
        else:
            self.participant_count_label.setText(
                f"👥 {total_count} total ({online_count} online, {offline_count} offline)"
            )

        # Get our JID for highlighting own entry
        account = self.account_manager.get_account(self.account_id)
        our_bare_jid = None
        if account and account.client:
            our_bare_jid = str(account.client.boundjid.bare).lower()

        # Get theme-aware highlight color
        highlight_brush = self._get_self_highlight_color()

        # Populate 5-column table
        self.participants_table.setRowCount(len(filtered_participants))

        for row_idx, p in enumerate(filtered_participants):
            # Check if this is our own entry
            is_self = our_bare_jid and p.get('jid', '').lower() == our_bare_jid

            # Column 0: Nickname
            nick_text = p.get('nickname') or ''
            if is_self and nick_text:
                nick_text = f"{nick_text} (You)"
            elif is_self:
                nick_text = "(You)"
            nick_item = QTableWidgetItem(nick_text)
            nick_item.setFlags(nick_item.flags() & ~Qt.ItemIsEditable)
            # Store participant data for context menu
            nick_item.setData(Qt.UserRole, p)
            if is_self:
                nick_item.setBackground(highlight_brush)
            if not nick_text:  # Offline user with no nickname
                nick_item.setForeground(Qt.gray)
            self.participants_table.setItem(row_idx, 0, nick_item)

            # Column 1: JID
            jid_text = p.get('jid', '(hidden)')
            jid_item = QTableWidgetItem(jid_text)
            jid_item.setFlags(jid_item.flags() & ~Qt.ItemIsEditable)
            if is_self:
                jid_item.setBackground(highlight_brush)
            if jid_text == '(hidden)':
                jid_item.setForeground(Qt.gray)
            self.participants_table.setItem(row_idx, 1, jid_item)

            # Column 2: Status
            status_text = p.get('status', 'Unknown')
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            if is_self:
                status_item.setBackground(highlight_brush)
            # Color code status
            if status_text == 'Online':
                status_item.setForeground(Qt.darkGreen)
            else:
                status_item.setForeground(Qt.gray)
            self.participants_table.setItem(row_idx, 2, status_item)

            # Column 3: Role
            role_text = p.get('role') or 'none'
            role_item = QTableWidgetItem(role_text)
            role_item.setFlags(role_item.flags() & ~Qt.ItemIsEditable)
            if is_self:
                role_item.setBackground(highlight_brush)
            if role_text == 'none' or not p['is_online']:
                role_item.setForeground(Qt.gray)
            self.participants_table.setItem(row_idx, 3, role_item)

            # Column 4: Affiliation
            affiliation_text = p.get('affiliation', 'none')
            affiliation_item = QTableWidgetItem(affiliation_text.capitalize())
            affiliation_item.setFlags(affiliation_item.flags() & ~Qt.ItemIsEditable)
            if is_self:
                affiliation_item.setBackground(highlight_brush)
            # Color code affiliation
            if affiliation_text == 'owner':
                affiliation_item.setForeground(QColor(255, 140, 0))  # Orange
            elif affiliation_text == 'admin':
                affiliation_item.setForeground(QColor(70, 130, 180))  # Steel blue
            elif affiliation_text == 'outcast':
                affiliation_item.setForeground(Qt.red)
            elif affiliation_text == 'none':
                affiliation_item.setForeground(Qt.gray)
            self.participants_table.setItem(row_idx, 4, affiliation_item)

    def _show_participant_context_menu(self, position):
        """Show context menu for participant with permission-based actions (adapts to online/offline)."""
        # Get selected row
        row = self.participants_table.rowAt(position.y())
        if row < 0:
            return

        # Get participant data from first column
        nick_item = self.participants_table.item(row, 0)
        if not nick_item:
            return

        participant = nick_item.data(Qt.UserRole)
        if not participant:
            return

        # Get our permissions
        account = self.account_manager.get_account(self.account_id)
        if not account:
            return

        our_affiliation = account.muc.get_own_affiliation(self.room_jid) or 'none'
        our_role = account.muc.get_own_role(self.room_jid) or 'none'

        # Don't allow changing own permissions
        our_bare_jid = str(account.client.boundjid.bare).lower() if account.client else None
        participant_jid = participant.get('jid', '').lower()
        if our_bare_jid and participant_jid == our_bare_jid:
            return  # This is us - don't show context menu

        # Permission checks
        can_manage_roles = our_role in ('moderator',) and participant['is_online']
        can_manage_affiliations = our_affiliation in ('owner', 'admin')
        is_owner = our_affiliation == 'owner'

        # Don't show menu if we have no permissions
        if not (can_manage_roles or can_manage_affiliations):
            return

        # Import QMenu
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)

        # ONLINE ONLY: Role management (moderators and above)
        if can_manage_roles and participant['is_online']:
            role_menu = menu.addMenu("Change Role")
            current_role = participant.get('role', 'none')

            for role in ['moderator', 'participant', 'visitor', 'none']:
                if role != current_role:
                    action = role_menu.addAction(role.capitalize())
                    action.triggered.connect(lambda checked=False, r=role: self._change_participant_role(participant, r))

        # Affiliation management (admins and owners - works for online AND offline)
        if can_manage_affiliations:
            affiliation_menu = menu.addMenu("Change Affiliation")
            current_affiliation = participant.get('affiliation', 'none')

            # Owners can set any affiliation, admins cannot make owners
            available_affiliations = ['owner', 'admin', 'member', 'none'] if is_owner else ['admin', 'member', 'none']

            for affiliation in available_affiliations:
                if affiliation != current_affiliation:
                    action = affiliation_menu.addAction(affiliation.capitalize())
                    action.triggered.connect(lambda checked=False, a=affiliation: self._change_participant_affiliation(participant, a))

        # Separator
        if (can_manage_roles and participant['is_online']) or can_manage_affiliations:
            menu.addSeparator()

        # ONLINE ONLY: Kick action (moderators and above)
        if can_manage_roles and participant['is_online']:
            kick_action = menu.addAction("Kick from Room")
            kick_action.triggered.connect(lambda: self._kick_participant(participant))

        # Ban/Unban actions (admins and owners - works for online AND offline)
        if can_manage_affiliations:
            if participant.get('affiliation') == 'outcast':
                unban_action = menu.addAction("Unban")
                unban_action.triggered.connect(lambda: self._change_participant_affiliation(participant, 'none'))
            else:
                ban_action = menu.addAction("Ban from Room")
                ban_action.triggered.connect(lambda: self._ban_participant(participant))

        # Show menu at cursor position
        menu.exec(self.participants_table.viewport().mapToGlobal(position))

    def _change_participant_role(self, participant: dict, new_role: str):
        """Change participant's role with optional reason (ONLINE ONLY)."""
        from PySide6.QtWidgets import QInputDialog

        nickname = participant.get('nickname') or participant.get('jid', 'Unknown')

        # Ask for reason (optional)
        reason, ok = QInputDialog.getText(
            self,
            "Change Role",
            f"Change {nickname}'s role to {new_role}.\nReason (optional):",
            QLineEdit.Normal,
            ""
        )

        if not ok:
            return  # User canceled

        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Error")
            msg.setText("Account not found")
            msg.show()
            return

        # Role changes require nickname (online users only)
        if not participant.get('nickname'):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Cannot Change Role")
            msg.setText("Cannot change role for offline users.")
            msg.show()
            return

        async def do_change():
            try:
                # Use slixmpp's set_role directly (requires nickname)
                await account.client.plugin['xep_0045'].set_role(
                    self.room_jid,
                    participant['nickname'],
                    new_role,
                    reason=reason
                )

                logger.info(f"Changed role of {participant['nickname']} to {new_role} in {self.room_jid}")

                # Reload participants to show updated role
                self._load_participants()

                # Non-blocking success message
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Role Changed")
                msg.setText(f"Successfully changed {nickname}'s role to {new_role}.")
                msg.show()

            except Exception as e:
                logger.error(f"Failed to change role: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to change role:\n{e}")
                msg.show()

        asyncio.create_task(do_change())

    def _change_participant_affiliation(self, participant: dict, new_affiliation: str):
        """Change participant's affiliation with optional reason (works for online AND offline)."""
        from PySide6.QtWidgets import QInputDialog

        display_name = participant.get('nickname') or participant.get('jid', 'Unknown')

        # Ask for reason (optional)
        reason, ok = QInputDialog.getText(
            self,
            "Change Affiliation",
            f"Change {display_name}'s affiliation to {new_affiliation}.\nReason (optional):",
            QLineEdit.Normal,
            ""
        )

        if not ok:
            return  # User canceled

        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Error")
            msg.setText("Account not found")
            msg.show()
            return

        # Affiliation changes require JID
        jid = participant.get('jid')
        if not jid or jid == '(hidden)':
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Cannot Change Affiliation")
            msg.setText("This room is anonymous. Real JIDs are not visible, so affiliation changes are not possible.")
            msg.show()
            return

        async def do_change():
            try:
                # Use slixmpp's set_affiliation
                await account.client.plugin['xep_0045'].set_affiliation(
                    self.room_jid,
                    new_affiliation,
                    jid=jid,
                    reason=reason
                )

                logger.info(f"Changed affiliation of {jid} to {new_affiliation} in {self.room_jid}")

                # Reload participants to show updated affiliation
                self._load_participants()

                # Non-blocking success message
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Affiliation Changed")
                msg.setText(f"Successfully changed {display_name}'s affiliation to {new_affiliation}.")
                msg.show()

            except Exception as e:
                logger.error(f"Failed to change affiliation: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to change affiliation:\n{e}")
                msg.show()

        asyncio.create_task(do_change())

    def _kick_participant(self, participant: dict):
        """Kick participant from room with optional reason (ONLINE ONLY)."""
        from PySide6.QtWidgets import QInputDialog

        nickname = participant.get('nickname') or participant.get('jid', 'Unknown')

        # Ask for reason (optional)
        reason, ok = QInputDialog.getText(
            self,
            "Kick Participant",
            f"Kick {nickname} from the room.\nReason (optional):",
            QLineEdit.Normal,
            ""
        )

        if not ok:
            return  # User canceled

        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Error")
            msg.setText("Account not found")
            msg.show()
            return

        # Kick requires nickname (online only)
        if not participant.get('nickname'):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Cannot Kick")
            msg.setText("Cannot kick offline users.")
            msg.show()
            return

        async def do_kick():
            try:
                # Kick = set role to 'none'
                await account.client.plugin['xep_0045'].set_role(
                    self.room_jid,
                    participant['nickname'],
                    'none',
                    reason=reason
                )

                logger.info(f"Kicked {participant['nickname']} from {self.room_jid}")

                # Reload participants to remove kicked user
                self._load_participants()

                # Non-blocking success message
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Participant Kicked")
                msg.setText(f"Successfully kicked {nickname} from the room.")
                msg.show()

            except Exception as e:
                logger.error(f"Failed to kick participant: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to kick participant:\n{e}")
                msg.show()

        asyncio.create_task(do_kick())

    def _ban_participant(self, participant: dict):
        """Ban participant from room (set affiliation to outcast) with optional reason."""
        from PySide6.QtWidgets import QInputDialog

        display_name = participant.get('nickname') or participant.get('jid', 'Unknown')

        # Ask for reason (optional)
        reason, ok = QInputDialog.getText(
            self,
            "Ban Participant",
            f"Ban {display_name} from the room.\nThis will prevent them from rejoining.\nReason (optional):",
            QLineEdit.Normal,
            ""
        )

        if not ok:
            return  # User canceled

        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Error")
            msg.setText("Account not found")
            msg.show()
            return

        # Ban requires JID
        jid = participant.get('jid')
        if not jid or jid == '(hidden)':
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Cannot Ban")
            msg.setText("This room is anonymous. Real JIDs are not visible, so banning is not possible.")
            msg.show()
            return

        async def do_ban():
            try:
                # Ban = set affiliation to 'outcast'
                await account.client.plugin['xep_0045'].set_affiliation(
                    self.room_jid,
                    'outcast',
                    jid=jid,
                    reason=reason
                )

                logger.info(f"Banned {jid} from {self.room_jid}")

                # Reload participants to remove banned user
                self._load_participants()

                # Non-blocking success message
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Information)
                msg.setWindowTitle("Participant Banned")
                msg.setText(f"Successfully banned {display_name} from the room.")
                msg.show()

            except Exception as e:
                logger.error(f"Failed to ban participant: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to ban participant:\n{e}")
                msg.show()

        asyncio.create_task(do_ban())

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

        # Check if joined and if user is room owner
        is_joined = (account.client and self.room_jid in account.client.joined_rooms)
        is_owner = account.muc.is_room_owner(self.room_jid)

        # Use shared room_info (already loaded by _load_room_info)
        room_info = self.room_info

        # Config tab: only visible if joined AND owner
        if not is_joined or not is_owner:
            self.tabs.setTabVisible(self.config_tab_index, False)
            return

        # Joined + Owner: show tab and load config
        self.tabs.setTabVisible(self.config_tab_index, True)

        # Fetch fresh config if not cached or if owner (to ensure fresh data)
        if not room_info or room_info.config_fetched is None:
            # Config not cached - fetch it now
            if account.client:
                async def fetch_fresh_config():
                    try:
                        logger.info(f"Fetching fresh room config for {self.room_jid}")
                        await account.muc.fetch_and_store_room_config(self.room_jid)
                        logger.info(f"Fresh room config fetched for {self.room_jid}")

                        # Check if dialog was closed during async operation
                        if self._destroyed:
                            logger.debug("Dialog destroyed during config fetch, skipping UI update")
                            return

                        # Reload config tab now that we have fresh data
                        self._load_config_sync()

                    except Exception as e:
                        logger.error(f"Failed to fetch fresh room config for {self.room_jid}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        # Check if dialog was closed
                        if self._destroyed:
                            return
                        # Show error in UI
                        self._load_config_sync()

                # Start async fetch
                asyncio.create_task(fetch_fresh_config())
                return

        # Config already cached, load it synchronously
        self._load_config_sync()

    def _load_config_sync(self):
        """Load room configuration synchronously from cache."""
        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            return

        # Reload room_info to get fresh data from barrel
        self.room_info = account.muc.get_room_info(self.room_jid)
        room_info = self.room_info

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
            self.config_allow_invites_checkbox.setEnabled(False)
            self.config_allow_subject_change_checkbox.setEnabled(False)
            self.config_whois_combo.setEnabled(False)
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

        # Tier 2 settings
        self.config_allow_invites_checkbox.setChecked(room_info.allow_invites)
        self.config_allow_subject_change_checkbox.setChecked(room_info.allow_subject_change)

        # Whois dropdown
        whois_value = room_info.whois or 'moderators'
        whois_index = self.config_whois_combo.findData(whois_value)
        if whois_index >= 0:
            self.config_whois_combo.setCurrentIndex(whois_index)

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
        self.config_allow_invites_checkbox.setEnabled(True)
        self.config_allow_subject_change_checkbox.setEnabled(True)
        self.config_whois_combo.setEnabled(True)
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

            # Reload settings to show updated values in form
            self._load_settings()

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
            'allowinvites': self.config_allow_invites_checkbox.isChecked(),
            'changesubject': self.config_allow_subject_change_checkbox.isChecked(),
            'whois': self.config_whois_combo.currentData(),
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

                    # Show progress: waiting for server to update disco#info
                    self.save_config_button.setText("Refreshing room info...")
                    logger.debug(f"Waiting 1.5s for server to update disco#info for {self.room_jid}")

                    # Wait for server to update its disco#info response
                    # (servers typically need a brief moment to propagate config changes)
                    await asyncio.sleep(1.5)

                    # Reload both tabs from fresh server data
                    # _load_room_info() will fetch fresh disco#info automatically
                    self._load_room_info()  # Fetches fresh disco + updates Info tab
                    self._load_config()     # Config tab reads from self.room_info

                    # Non-blocking success message
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Configuration Saved")
                    msg.setText("Room configuration saved and room features refreshed successfully.")
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

                # Check if dialog was closed during async operation
                if self._destroyed:
                    logger.debug("Dialog destroyed during config refresh, skipping UI update")
                    return

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
                # Check if dialog was closed
                if self._destroyed:
                    return
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

    def _on_edit_subject(self):
        """Show dialog to edit room subject."""
        from PySide6.QtWidgets import QInputDialog

        # Get current subject
        has_subject = self.subject_label.property("has_subject")
        if has_subject:
            current_subject = self.subject_label.text()
        else:
            current_subject = ""

        # Show input dialog
        new_subject, ok = QInputDialog.getText(
            self,
            "Edit Room Subject",
            "Enter new room subject/topic:",
            QLineEdit.Normal,
            current_subject
        )

        if not ok:
            return  # User canceled

        # Get account
        account = self.account_manager.get_account(self.account_id)
        if not account:
            QMessageBox.warning(self, "Error", "Account not found")
            return

        # Disable button during update
        self.edit_subject_button.setEnabled(False)
        self.edit_subject_button.setText("Updating...")

        async def do_update():
            try:
                # Send subject change via DrunkXMPP
                success = await account.client.change_room_subject(self.room_jid, new_subject)

                if success:
                    # Update display immediately
                    if new_subject:
                        self.subject_label.setText(new_subject)
                        self.subject_label.setProperty("has_subject", True)
                    else:
                        self.subject_label.setText("(No subject set)")
                        self.subject_label.setProperty("has_subject", False)

                    # Non-blocking success message
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Information)
                    msg.setWindowTitle("Subject Updated")
                    msg.setText("Room subject has been changed successfully.")
                    msg.show()

                    logger.info(f"Changed subject for {self.room_jid}")
                else:
                    # Non-blocking warning
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Warning)
                    msg.setWindowTitle("Update Failed")
                    msg.setText("Could not change room subject. You may not have permission.")
                    msg.show()

            except Exception as e:
                logger.error(f"Failed to change subject: {e}")
                import traceback
                logger.error(traceback.format_exc())
                # Non-blocking error
                msg = QMessageBox(self)
                msg.setIcon(QMessageBox.Critical)
                msg.setWindowTitle("Error")
                msg.setText(f"Failed to change subject:\n{e}")
                msg.show()

            finally:
                # Re-enable button
                self.edit_subject_button.setEnabled(True)
                self.edit_subject_button.setText("✏️ Edit Subject")

        # Run async task
        asyncio.create_task(do_update())

    def _on_leave_room(self):
        """Handle Leave Room button click - emit signal for main_window to handle."""
        # Emit signal - main_window will handle the actual leaving logic
        self.leave_room_requested.emit(self.account_id, self.room_jid)

        # Close dialog (main_window will show confirmation and handle everything)
        self.accept()

    def _on_destroy_room(self):
        """Handle Destroy Room button click - emit signal for main_window to handle."""
        # Emit signal - main_window will handle the actual destruction logic
        # (confirmation dialogs and async operations are handled in MUCManager)
        self.destroy_room_requested.emit(self.account_id, self.room_jid)

        # Close dialog (main_window will show confirmation and handle everything)
        self.accept()
