"""
Main application window for Siproxylin.

Layout:
- Menu bar (File, Edit, View)
- Left sidebar: Contact list
- Right panel: Chat view
- Bottom: Input area
"""

import logging
import asyncio
import base64
import subprocess
from datetime import datetime
from typing import Optional
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMenuBar, QMenu, QLabel, QSplitter, QDialog, QStatusBar, QMessageBox
)
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QAction, QActionGroup

from ..db.database import get_db
from ..utils.paths import get_paths
from .log_viewer import LogViewer
from .account_dialog import AccountDialog
from .registration_wizard import RegistrationWizard
from .contact_dialog import ContactDialog
from .join_room_dialog import JoinRoomDialog
from .contact_details_dialog import ContactDetailsDialog
from .contact_list import ContactListWidget
from .chat_view import ChatViewWidget
from ..core import get_account_manager
from ..core.contact_manager import get_contact_manager
from ..styles.theme_manager import get_theme_manager
from ..services.notification import get_notification_service
from .managers import CallManager, NotificationManager, MenuManager, SubscriptionManager, MessageManager, DialogManager


logger = logging.getLogger('siproxylin.main_window')


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()

        self.db = get_db()
        self.paths = get_paths()
        self.account_manager = get_account_manager()
        self.contact_manager = get_contact_manager()
        self.theme_manager = get_theme_manager(config_dir=self.paths.config_dir)
        self.notification_service = get_notification_service()

        # Track open log viewer windows
        self.log_viewers = {}  # {(account_id, log_type): LogViewer}

        # Shutdown flag (set by signal handler to skip gRPC shutdown)
        self._signal_shutdown = False

        # Track app start time for uptime
        import time
        self.app_start_time = time.time()

        # Window setup
        self.setWindowTitle("Siproxylin")
        self.setGeometry(100, 100, 1200, 800)

        # Setup UI first (creates contact_list and chat_view widgets)
        self._create_central_widget()
        self._setup_status_bar()

        # Initialize managers after UI widgets are created
        # Notification manager - handles OS notifications
        self.notification_manager = NotificationManager(self)

        # Call manager - handles call windows, dialogs, and Go call service
        self.call_manager = CallManager(self)
        # Link notification_manager to call_manager
        self.call_manager.notification_manager = self.notification_manager

        # Menu manager - handles menu bar and menu actions
        self.menu_manager = MenuManager(self)
        self.menu_manager.create_menu_bar()

        # Subscription manager - handles subscriptions and blocking
        self.subscription_manager = SubscriptionManager(self)

        # Message manager - handles sending/editing messages and files
        self.message_manager = MessageManager(self)
        # Connect chat_view message signals to message_manager
        self.chat_view.send_message.connect(self.message_manager.on_send_message)
        self.chat_view.send_file.connect(self.message_manager.on_send_file)
        self.chat_view.edit_message.connect(self.message_manager.on_edit_message)
        self.chat_view.send_reply.connect(self.message_manager.on_send_reply)

        # Dialog manager - handles dialog creation and launching
        self.dialog_manager = DialogManager(self)

        # Load saved theme (or default to dark)
        self.theme_manager.load_theme(self.theme_manager.current_theme, save=False)

        # Set initial theme checkmark in menu
        current_theme = self.theme_manager.current_theme
        if current_theme in self.menu_manager.theme_actions:
            self.menu_manager.theme_actions[current_theme].setChecked(True)

        logger.debug("Main window created")

    def setup_accounts(self):
        """Setup after accounts are loaded."""
        # Start Go call service (use ensure_future - works with set but not-yet-running loop)
        if self.call_manager.go_call_service:
            asyncio.ensure_future(self.call_manager.start_service())

        # Start timer to refresh chat view for receipt updates every 2 seconds
        self.receipt_timer = QTimer(self)
        self.receipt_timer.timeout.connect(self._update_chat_receipts)
        self.receipt_timer.start(2000)  # Update every 2 seconds

        # Connect signals from all accounts
        for account_id, account in self.account_manager.accounts.items():
            account.connection_state_changed.connect(self._on_connection_state_changed)
            account.roster_updated.connect(self._on_roster_updated)
            account.message_received.connect(self._on_message_received)
            account.chat_state_changed.connect(self._on_chat_state_changed)
            account.presence_changed.connect(self._on_presence_changed)
            account.muc_invite_received.connect(self._on_muc_invite_received)
            account.muc_role_changed.connect(self._on_muc_role_changed)
            account.avatar_updated.connect(self._on_avatar_updated)
            account.nickname_updated.connect(self._on_nickname_updated)

            # Subscription signals - handled by SubscriptionManager
            self.subscription_manager.connect_account_signals(account)

            # Call signals (DrunkCALL integration) - handled by CallManager
            self.call_manager.connect_account_signals(account)

        # Load roster into contact list
        self.contact_list.load_roster()

        logger.debug("Setup complete")

    def _create_central_widget(self):
        """Create central widget with contact list and chat view."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QHBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main splitter (contact list | chat view)
        self.splitter = QSplitter(Qt.Horizontal)

        # Left panel: Contact list
        self.contact_list = ContactListWidget()
        self.contact_list.contact_selected.connect(self._on_contact_selected)
        self.contact_list.home_requested.connect(self._on_home_requested)
        self.contact_list.call_log_requested.connect(self._on_call_log_requested)
        self.contact_list.contacts_requested.connect(self._on_contacts_requested)
        self.contact_list.settings_requested.connect(self._on_settings_requested)
        self.contact_list.edit_contact_requested.connect(self._on_edit_contact_from_roster)
        self.contact_list.view_omemo_keys_requested.connect(self._on_view_omemo_keys)
        self.contact_list.manage_subscription_requested.connect(self._on_manage_subscription)
        self.contact_list.block_contact_requested.connect(self._on_block_contact_from_roster)
        self.contact_list.delete_chat_requested.connect(self._on_delete_chat)
        self.contact_list.delete_contact_requested.connect(self._on_delete_contact_from_roster)
        self.contact_list.delete_and_block_requested.connect(self._on_delete_and_block)

        # MUC context menu signals
        self.contact_list.view_muc_details_requested.connect(self._on_view_muc_details)
        self.contact_list.leave_muc_requested.connect(self.leave_muc)

        # Account context menu signals
        self.contact_list.account_connect_requested.connect(self._on_account_connect)
        self.contact_list.account_disconnect_requested.connect(self._on_account_disconnect)
        self.contact_list.account_details_requested.connect(self._on_edit_account)  # Reuse existing method
        self.contact_list.add_contact_requested.connect(self._on_add_contact_for_account)
        self.contact_list.join_room_requested.connect(self._on_join_room_for_account)
        # Set minimum width to prevent collapsing (150px minimum)
        self.contact_list.setMinimumWidth(150)

        # Right panel: Chat view (pass self as parent for main_window reference)
        self.chat_view = ChatViewWidget(parent=self)
        # Message signals will be connected after MessageManager is initialized
        self.chat_view.add_account_requested.connect(self._on_new_account)
        self.chat_view.create_account_requested.connect(self._on_create_account)
        # Set minimum width to prevent collapsing (400px minimum)
        self.chat_view.setMinimumWidth(400)

        self.splitter.addWidget(self.contact_list)
        self.splitter.addWidget(self.chat_view)

        # Prevent widgets from collapsing completely
        self.splitter.setCollapsible(0, False)  # Contact list can't collapse
        self.splitter.setCollapsible(1, False)  # Chat view can't collapse

        # Set initial sizes (contact list: 250px, chat view: rest)
        self.splitter.setSizes([250, 950])

        layout.addWidget(self.splitter)

    def _setup_status_bar(self):
        """Setup status bar with stats."""
        status_bar = self.statusBar()
        status_bar.show()

        # Create labels for each stat (font size controlled by theme)
        self.status_uptime_label = QLabel()
        self.status_accounts_label = QLabel()
        self.status_messages_label = QLabel()
        self.status_calls_label = QLabel()

        # Create separators
        sep1 = QLabel(" | ")
        sep2 = QLabel(" | ")
        sep3 = QLabel(" | ")

        # Add labels to status bar (left to right: uptime first)
        status_bar.addWidget(self.status_uptime_label)
        status_bar.addWidget(sep1)
        status_bar.addWidget(self.status_accounts_label)
        status_bar.addWidget(sep2)
        status_bar.addWidget(self.status_messages_label)
        status_bar.addWidget(sep3)
        status_bar.addWidget(self.status_calls_label)

        # Update stats initially
        self._update_status_bar_stats()

        # Setup timer for uptime updates (every 60 seconds)
        from PySide6.QtCore import QTimer
        self.status_bar_timer = QTimer(self)
        self.status_bar_timer.timeout.connect(self._update_status_bar_uptime)
        self.status_bar_timer.start(60000)  # Update every minute

    def _count_connection_states(self) -> dict:
        """Count connection states for loaded (enabled) accounts."""
        states = {'connected': 0, 'connecting': 0, 'disconnected': 0}

        for account in self.account_manager.accounts.values():
            status = account.connection._status
            if status in states:
                states[status] += 1

        return states

    def _update_status_bar_stats(self):
        """Update all status bar statistics."""
        # Get all statistics via unified API
        stats = self.db.get_global_statistics()

        # Get connection states from AccountManager (in-memory)
        conn_states = self._count_connection_states()

        # Update status bar labels
        self.status_accounts_label.setText(
            f"Accounts: {stats['accounts']['total']} total, {stats['accounts']['enabled']} enabled "
            f"({conn_states['connected']} connected)"
        )

        self.status_messages_label.setText(
            f"Messages: {stats['messages']['total']} total, "
            f"{stats['messages']['unread']} unread, {stats['messages']['unsent']} unsent"
        )

        self.status_calls_label.setText(
            f"Calls: {stats['calls']['total']} total, "
            f"{stats['calls']['incoming']} in, {stats['calls']['outgoing']} out, {stats['calls']['missed']} missed"
        )

        # Update uptime
        self._update_status_bar_uptime()

    def _update_status_bar_uptime(self):
        """Update only the uptime in status bar."""
        import time
        uptime_seconds = int(time.time() - self.app_start_time)
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        self.status_uptime_label.setText(f"Online: {hours}h {minutes}m")

    # =========================================================================
    # Account Management Handlers
    # =========================================================================

    def _on_account_saved(self, account_id: int, enabled: bool):
        """
        Handle account save from AccountDialog.

        Args:
            account_id: Account ID that was saved
            enabled: Whether the account is enabled
        """
        logger.info(f"Account {account_id} saved (enabled={enabled})")

        # Check if this is a new account or existing
        is_new = account_id not in self.account_manager.accounts

        if is_new:
            logger.debug("Account saved successfully")
            # New account - load and connect if enabled
            if enabled:
                logger.debug(f"Loading new account {account_id}")
                account_data = self.db.fetchone("SELECT * FROM account WHERE id = ?", (account_id,))
                if account_data:
                    from ..core import XMPPAccount
                    account = XMPPAccount(account_id, dict(account_data))

                    # Connect signals
                    account.roster_updated.connect(self._on_roster_updated)
                    account.message_received.connect(self._on_message_received)
                    account.chat_state_changed.connect(self._on_chat_state_changed)
                    account.muc_invite_received.connect(self._on_muc_invite_received)
                    account.muc_role_changed.connect(self._on_muc_role_changed)
                    account.avatar_updated.connect(self._on_avatar_updated)
                    account.subscription_request_received.connect(self._on_subscription_request_received)
                    account.subscription_changed.connect(self._on_subscription_changed)

                    # Connect call signals via CallManager
                    self.call_manager.connect_account_signals(account)

                    self.account_manager.accounts[account_id] = account
                    account.connect()
                    logger.info(f"Account {account_id} connected")
            else:
                logger.debug(f"New account {account_id} is disabled, not connecting")
        else:
            logger.debug(f"Account {account_id} updated successfully")
            # Existing account - handle enable/disable
            account = self.account_manager.get_account(account_id)
            if account:
                if enabled:
                    # Reload account settings (disconnects and reconnects if connected)
                    logger.debug(f"Reloading account {account_id}")
                    account.reload_and_reconnect()
                else:
                    # Disconnect disabled account
                    logger.debug(f"Disconnecting disabled account {account_id}")
                    account.disconnect()

        # Update UI components
        self.menu_manager.populate_edit_menu()
        self.menu_manager.populate_view_menu()
        self.contact_list.load_roster()

        logger.debug(f"UI updated after account {account_id} save")

    def _on_account_deleted(self, account_id: int):
        """
        Handle account deletion from AccountDialog.

        Args:
            account_id: Account ID that was deleted
        """
        logger.info(f"Account {account_id} deleted, cleaning up UI")

        # Disconnect and remove account from AccountManager
        account = self.account_manager.get_account(account_id)
        if account:
            logger.debug(f"Disconnecting account {account_id}")
            account.disconnect()
            del self.account_manager.accounts[account_id]

        # Clear chat view if showing deleted account
        if hasattr(self, 'current_account_id') and self.current_account_id == account_id:
            logger.debug(f"Clearing chat view (was showing deleted account {account_id})")
            self.chat_view.clear()
            self.current_account_id = None
            self.current_jid = None

        # Update UI components (same as account save)
        self.menu_manager.populate_edit_menu()
        self.menu_manager.populate_view_menu()
        self.contact_list.load_roster()

        logger.debug(f"UI cleaned up after account {account_id} deletion")

    def _on_contact_saved(self, account_id: int, jid: str, name: str, can_see_theirs: bool, they_can_see_ours: bool):
        """
        Handle contact save from ContactDialog.

        Args:
            account_id: Account ID
            jid: Contact JID
            name: Contact display name (can be empty)
            can_see_theirs: Whether to request seeing their presence
            they_can_see_ours: Whether to allow them to see our presence
        """
        logger.info(f"Contact saved: {jid} for account {account_id} (name='{name}', can_see_theirs={can_see_theirs}, they_can_see_ours={they_can_see_ours})")

        # Get account and check if connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot modify contact while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Handle contact operations via contact manager
        try:
            # Check for deletion: empty name AND both subscriptions False
            if name == "" and not can_see_theirs and not they_can_see_ours:
                # Delete contact
                logger.debug(f"Removing contact {jid}")
                asyncio.create_task(
                    self.contact_manager.remove_contact(account_id, account.client, jid)
                )
            else:
                # Always update contact name (even if empty - clears roster.name on server)
                asyncio.create_task(
                    self.contact_manager.update_contact_name(account_id, account.client, jid, name or '')
                )

                # Handle subscription changes using shared method
                self._update_subscription(account_id, jid, can_see_theirs, they_can_see_ours)

            # Refresh contact list
            self.contact_list.load_roster()

        except Exception as e:
            logger.error(f"Failed to save contact: {e}")
            QMessageBox.critical(self, "Error", f"Failed to save contact:\n{e}")

    def _select_account_dialog(self, title: str, message: str, connected_only: bool = True) -> Optional[int]:
        """
        Show account selection dialog.

        Args:
            title: Dialog title
            message: Dialog message
            connected_only: If True, only show connected accounts (default: True)

        Returns:
            Selected account ID or None if cancelled
        """
        from PySide6.QtWidgets import QInputDialog

        # Build list of accounts (filter by connection if requested)
        accounts = []
        account_ids = []
        for account_id in sorted(self.account_manager.accounts.keys()):
            # Filter by connection status if needed
            if connected_only:
                account = self.account_manager.get_account(account_id)
                if not account or not account.is_connected():
                    continue

            account_data = self.db.fetchone("SELECT bare_jid, nickname FROM account WHERE id = ?", (account_id,))
            if account_data:
                display_name = account_data['nickname'] or account_data['bare_jid']
                accounts.append(f"Account {account_id}: {display_name}")
                account_ids.append(account_id)

        if not accounts:
            return None

        # If only one account, return it directly
        if len(accounts) == 1:
            return account_ids[0]

        # Show selection dialog
        item, ok = QInputDialog.getItem(self, title, message, accounts, 0, False)
        if ok and item:
            # Extract account ID from selection
            idx = accounts.index(item)
            return account_ids[idx]

        return None

    # =========================================================================
    # Menu Action Handlers
    # =========================================================================

    def _on_new_account(self):
        """Delegate to DialogManager."""
        self.dialog_manager.show_new_account_dialog()

    def _on_create_account(self):
        """Delegate to DialogManager."""
        self.dialog_manager.show_create_account_wizard()

    def _on_account_registered(self, account_id):
        """Handle account registered via wizard."""
        logger.info(f"Account {account_id} registered via wizard")

        # Reload account manager to include new account
        # load_accounts() already connects enabled accounts
        self.account_manager.load_accounts()

        # Setup signals for new account
        self.setup_accounts()

        # Refresh UI components (including Edit menu)
        self.menu_manager.populate_edit_menu()
        self.menu_manager.populate_view_menu()
        self.contact_list.load_roster()

    def _on_new_contact(self):
        """Handle File -> New Contact."""
        logger.debug("New Contact requested")

        # Check if any accounts exist
        if not self.account_manager.accounts:
            QMessageBox.warning(self, "No Accounts", "Please create an account first.")
            return

        # Let user select account (connected accounts only)
        account_id = self._select_account_dialog("Select Account", "Add contact to which account?")
        if account_id is None:
            return

        dialog = ContactDialog(account_id=account_id, parent=self)
        dialog.contact_saved.connect(self._on_contact_saved)
        if dialog.exec() == QDialog.Accepted:
            logger.debug("Contact saved successfully")

    def _on_new_group(self):
        """Handle File -> New Group (Join MUC room)."""
        logger.debug("New Group (MUC) requested")

        # Check if any accounts exist
        if not self.account_manager.accounts:
            QMessageBox.warning(self, "No Accounts", "Please create an account first.")
            return

        # Let user select account if multiple accounts
        account_id = self._select_account_dialog("Select Account", "Join room with which account?")
        if account_id is None:
            return

        # Check if selected account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot join room while offline.\n\n"
                f"Please connect the account first."
            )
            return

        dialog = JoinRoomDialog(account_id=account_id, parent=self)
        if dialog.exec() == QDialog.Accepted:
            # Get joined room info
            room_jid = dialog.room_jid
            nick = dialog.nick
            password = dialog.password if dialog.password else None

            logger.info(f"Joining room: {room_jid} as {nick}")

            # Add room to client configuration and join
            account = self.account_manager.get_account(account_id)
            if account and account.client:
                asyncio.create_task(account.add_and_join_room(room_jid, nick, password))
                logger.debug(f"Room join initiated: {room_jid}")

                # Refresh contact list to show new room
                self.contact_list.load_roster()
            else:
                QMessageBox.warning(self, "Error", "Account not connected.")

    def _on_settings(self):
        """Delegate to DialogManager."""
        self.dialog_manager.show_settings_dialog()

    def _on_copy(self):
        """Handle Edit -> Copy."""
        pass  # Handled by Qt automatically

    def _on_paste(self):
        """Handle Edit -> Paste."""
        pass  # Handled by Qt automatically

    def _on_edit_account(self, account_id: int):
        """Delegate to DialogManager."""
        self.dialog_manager.show_edit_account_dialog(account_id)


    def _on_contact_selected(self, account_id: int, jid: str):
        """
        Handle contact selection from contact list.

        Args:
            account_id: Account ID
            jid: Contact JID
        """
        logger.debug(f"Contact selected: {jid} (account {account_id})")
        self.chat_view.load_conversation(account_id, jid)

        # Refresh contact list (in case conversation was just created)
        self.contact_list.load_roster()

        # Select the contact in the roster (useful when opened from dialog)
        self.contact_list.select_contact(account_id, jid)

        # Dismiss notification for this conversation (with elegant delay)
        QTimer.singleShot(500, lambda: self.notification_service.dismiss_notification(account_id, jid))

        # Update unread indicators after opening chat
        # Use a small delay to ensure displayed markers are sent and DB is updated
        QTimer.singleShot(100, lambda: self.contact_list.update_unread_indicators(account_id, jid))

    def _on_home_requested(self):
        """Handle HOME button click - return to welcome page."""
        logger.debug("HOME button clicked - returning to welcome page")

        # Stop typing notifications timers
        self.chat_view.input_field.reset_chat_state()

        # Switch to welcome page (Page 0) - keeps state for draft preservation
        self.chat_view.stack.setCurrentIndex(0)

        # Clear roster selection
        self.contact_list.contact_tree.clearSelection()

    def _on_call_log_requested(self):
        """Handle call log button click - open View -> Calls dialog."""
        logger.debug("Call log button clicked")
        self.menu_manager.on_view_call_log()

    def _on_contacts_requested(self):
        """Handle contacts button click - open Contacts -> Manage Contacts dialog."""
        logger.debug("Contacts button clicked")
        self._on_manage_contacts()

    def _on_settings_requested(self):
        """Handle settings button click - open File -> Settings dialog."""
        logger.debug("Settings button clicked")
        self._on_settings()

    def _on_edit_contact_from_roster(self, account_id: int, jid: str, roster_id: int):
        """
        Handle View Details from contact context menu.
        Opens contact details dialog with OMEMO keys (same as chat header gear icon).

        Args:
            account_id: Account ID
            jid: Contact JID
            roster_id: Roster entry ID
        """
        logger.debug(f"View details requested: {jid} (roster_id: {roster_id})")

        # TEST: Use new unified ContactDetailsDialog
        self._test_open_contact_details_dialog(account_id, jid)

    def _on_view_omemo_keys(self, account_id: int, jid: str):
        """
        Handle View OMEMO Keys from gear button in chat header.

        Args:
            account_id: Account ID
            jid: Contact JID
        """
        logger.debug(f"View OMEMO keys requested for {jid}")

        # Use unified ContactDetailsDialog (opens to OMEMO tab)
        account = self.account_manager.get_account(account_id)
        if account and account.client:
            asyncio.create_task(self._sync_and_show_contact_details_dialog(account, jid))
        else:
            # Offline - show what's in DB
            dialog = ContactDetailsDialog(account_id, jid, self)
            dialog.contact_saved.connect(self._on_contact_saved)
            dialog.block_status_changed.connect(self._on_block_status_changed)
            dialog.setAttribute(Qt.WA_DeleteOnClose)
            dialog.show()

    def _on_manage_contacts(self):
        """Handle Contacts -> Manage Contacts."""
        logger.debug("Manage contacts requested")

        from .contacts_manager_dialog import ContactsManagerDialog

        dialog = ContactsManagerDialog(show_only_blocked=False, parent=self)
        dialog.contact_modified.connect(self.contact_list.refresh)
        dialog.delete_contact_requested.connect(self._on_delete_contact_from_roster)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def _on_view_blocked_contacts(self):
        """Handle Contacts -> View Blocked Contacts."""
        logger.debug("View blocked contacts requested")

        from .contacts_manager_dialog import ContactsManagerDialog

        dialog = ContactsManagerDialog(show_only_blocked=True, parent=self)
        dialog.contact_modified.connect(self.contact_list.refresh)
        dialog.delete_contact_requested.connect(self._on_delete_contact_from_roster)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def _on_about(self):
        """Delegate to DialogManager."""
        self.dialog_manager.show_about_dialog()

    def _test_open_contact_details_dialog(self, account_id: int, jid: str):
        """
        TEST METHOD: Open new unified ContactDetailsDialog.

        This method opens the new ContactDetailsDialog which combines:
        - Contact info
        - Settings (name, notifications, etc.)
        - Presence subscription
        - OMEMO keys

        Once tested, this will replace _on_edit_contact_from_roster and _on_view_omemo_keys.
        """
        logger.debug(f"TEST: Opening ContactDetailsDialog for {jid}")

        # Sync OMEMO devices to database before showing dialog (if connected)
        account = self.account_manager.get_account(account_id)
        if account and account.client:
            asyncio.create_task(self._sync_and_show_contact_details_dialog(account, jid))
        else:
            # Offline - show what's in DB
            dialog = ContactDetailsDialog(account_id, jid, self)
            dialog.contact_saved.connect(self._on_contact_saved)
            dialog.block_status_changed.connect(self._on_block_status_changed)
            dialog.setAttribute(Qt.WA_DeleteOnClose)
            dialog.show()

    async def _sync_and_show_contact_details_dialog(self, account, jid: str):
        """Helper to sync OMEMO devices then show ContactDetailsDialog."""
        try:
            # Sync OMEMO devices
            if account.omemo_available:
                await account.sync_omemo_devices(jid)
                own_jid = account.client.boundjid.bare
                await account.sync_omemo_devices(own_jid)
        except Exception as e:
            logger.warning(f"Failed to sync OMEMO devices: {e}")

        # Show dialog with synced data
        dialog = ContactDetailsDialog(account.account_id, jid, self)
        dialog.contact_saved.connect(self._on_contact_saved)
        dialog.block_status_changed.connect(self._on_block_status_changed)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def _on_block_contact_from_roster(self, account_id: int, jid: str, roster_id: int, currently_blocked: bool):
        """
        Handle Block/Unblock Contact from context menu.

        Args:
            account_id: Account ID
            jid: Contact JID
            roster_id: Roster entry ID
            currently_blocked: Current blocked status
        """
        action = "Unblock" if currently_blocked else "Block"
        logger.debug(f"{action} contact requested: {jid}")

        # Check if account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot {action.lower()} contact while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Confirm action
        reply = QMessageBox.question(
            self,
            f"{action} Contact",
            f"Are you sure you want to {action.lower()} '{jid}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Use unified method to apply block/unblock
            new_blocked = not currently_blocked
            self._apply_block_status(account_id, jid, new_blocked)

            QMessageBox.information(self, "Success", f"Contact {action.lower()}ed successfully")

        except Exception as e:
            logger.error(f"Failed to {action.lower()} contact: {e}")
            QMessageBox.critical(self, "Error", f"Failed to {action.lower()} contact:\n{e}")

    def _on_delete_chat(self, account_id: int, jid: str):
        """
        Handle Delete History from context menu.
        Deletes all messages (local DB + server MAM), keeps contact.

        Args:
            account_id: Account ID
            jid: Contact JID
        """
        logger.debug(f"Delete history requested: {jid}")

        # Confirm deletion
        reply = QMessageBox.warning(
            self,
            "Delete History",
            f"Delete all message history with '{jid}'?\n\n"
            f"This will:\n"
            f"- DELETE all local messages\n"
            f"- Try to delete from server (MAM)\n"
            f"- Keep contact in roster\n"
            f"- Keep chat window open (empty)\n\n"
            f"This action cannot be undone!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Get JID ID for message deletion
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid,))
            jid_id = jid_row['id'] if jid_row else None

            if not jid_id:
                QMessageBox.warning(self, "Error", f"Contact {jid} not found in database")
                return

            # Delete message history (local)
            deleted_msgs = self.db.execute(
                "DELETE FROM message WHERE account_id = ? AND counterpart_id = ?",
                (account_id, jid_id)
            ).rowcount

            # Delete file transfers (attachments)
            deleted_files = self.db.execute(
                "DELETE FROM file_transfer WHERE account_id = ? AND counterpart_id = ?",
                (account_id, jid_id)
            ).rowcount

            self.db.commit()
            logger.info(f"Deleted {deleted_msgs} messages and {deleted_files} file transfers for {jid}")

            # TODO: Try to delete from server MAM (XEP-0313, best effort)
            # Most servers don't support this yet

            # Clear the chat view if currently open
            if hasattr(self, 'chat_view') and self.chat_view.current_account_id == account_id and self.chat_view.current_jid == jid:
                self.chat_view.clear()
                # Reload empty conversation
                self.chat_view.load_conversation(account_id, jid)
                logger.debug(f"Chat view cleared and reloaded (empty) for {jid}")

            QMessageBox.information(
                self,
                "Success",
                f"Deleted {deleted_msgs} messages and {deleted_files} file transfers with '{jid}'\n\n"
                f"Contact remains in roster.\n"
                f"Note: Server MAM deletion not yet implemented."
            )
            logger.info(f"History deleted for {jid} ({deleted_msgs} messages, {deleted_files} files)")

        except Exception as e:
            logger.error(f"Failed to delete history: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete history:\n{e}")

    def _on_delete_contact_from_roster(self, account_id: int, jid: str, roster_id: int):
        """
        Handle Delete Contact from context menu.

        Args:
            account_id: Account ID
            jid: Contact JID
            roster_id: Roster entry ID
        """
        logger.debug(f"Delete contact requested: {jid}")

        # Check if account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot remove contact while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Confirm deletion
        reply = QMessageBox.warning(
            self,
            "Delete Contact",
            f"Are you sure you want to delete '{jid}'?\n\n"
            f"This will:\n"
            f"- Remove contact from your roster\n"
            f"- Revoke presence subscriptions\n"
            f"- DELETE ALL MESSAGE HISTORY (local)\n\n"
            f"This action cannot be undone!",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Get JID ID for message deletion
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid,))
            jid_id = jid_row['id'] if jid_row else None

            # Send roster removal IQ to server
            asyncio.create_task(account.client.remove_roster_item(jid))
            logger.debug(f"Sent roster removal IQ for {jid}")

            # Delete message history (local)
            if jid_id:
                deleted_msgs = self.db.execute(
                    "DELETE FROM message WHERE account_id = ? AND counterpart_id = ?",
                    (account_id, jid_id)
                ).rowcount
                deleted_files = self.db.execute(
                    "DELETE FROM file_transfer WHERE account_id = ? AND counterpart_id = ?",
                    (account_id, jid_id)
                ).rowcount
                logger.debug(f"Deleted {deleted_msgs} messages and {deleted_files} file transfers for {jid}")

            # Delete from roster
            self.db.execute("DELETE FROM roster WHERE id = ?", (roster_id,))
            self.db.commit()

            # Close chat window if open
            if hasattr(self, 'chat_view') and self.chat_view.current_account_id == account_id and self.chat_view.current_jid == jid:
                self.chat_view.clear()

            self.contact_list.refresh()
            QMessageBox.information(self, "Success", f"Contact '{jid}' and all message history deleted")
            logger.info(f"Contact {jid} removed from roster (history deleted)")

        except Exception as e:
            logger.error(f"Failed to remove contact: {e}")
            QMessageBox.critical(self, "Error", f"Failed to remove contact:\n{e}")

    def _on_delete_and_block(self, account_id: int, jid: str, roster_id: int):
        """
        Handle Delete & Block from context menu.
        Nuclear option: Delete all history + Block + Remove from roster.

        Args:
            account_id: Account ID
            jid: Contact JID
            roster_id: Roster entry ID
        """
        logger.debug(f"Delete & Block requested: {jid}")

        # Check if account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot delete & block while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Confirm deletion with severe warning
        reply = QMessageBox.warning(
            self,
            "Delete & Block Contact",
            f"⚠️ NUCLEAR OPTION ⚠️\n\n"
            f"This will IMMEDIATELY:\n"
            f"- DELETE ALL MESSAGE HISTORY (local)\n"
            f"- BLOCK '{jid}' (XEP-0191)\n"
            f"- REMOVE from roster\n"
            f"- REVOKE presence subscriptions\n\n"
            f"This action CANNOT be undone!\n\n"
            f"Are you absolutely sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Get JID ID for message deletion
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid,))
            jid_id = jid_row['id'] if jid_row else None

            # 1. Block contact (XEP-0191)
            asyncio.create_task(account.client.block_contact(jid))
            logger.debug(f"Sent block IQ for {jid}")

            # 2. Remove from roster
            asyncio.create_task(account.client.remove_roster_item(jid))
            logger.debug(f"Sent roster removal IQ for {jid}")

            # 3. Delete message history (local)
            deleted_msgs = 0
            deleted_files = 0
            if jid_id:
                deleted_msgs = self.db.execute(
                    "DELETE FROM message WHERE account_id = ? AND counterpart_id = ?",
                    (account_id, jid_id)
                ).rowcount
                deleted_files = self.db.execute(
                    "DELETE FROM file_transfer WHERE account_id = ? AND counterpart_id = ?",
                    (account_id, jid_id)
                ).rowcount
                logger.debug(f"Deleted {deleted_msgs} messages and {deleted_files} file transfers for {jid}")

            # 4. Update roster DB (mark as blocked + delete)
            self.db.execute("UPDATE roster SET blocked = 1 WHERE id = ?", (roster_id,))
            self.db.execute("DELETE FROM roster WHERE id = ?", (roster_id,))
            self.db.commit()

            # 5. Close chat window if open
            if hasattr(self, 'chat_view') and self.chat_view.current_account_id == account_id and self.chat_view.current_jid == jid:
                self.chat_view.clear()

            # 6. Refresh UI
            self.contact_list.refresh()

            QMessageBox.information(
                self,
                "Success",
                f"Contact '{jid}' has been:\n"
                f"- Blocked (XEP-0191)\n"
                f"- Removed from roster\n"
                f"- History deleted ({deleted_msgs} messages, {deleted_files} files)"
            )
            logger.info(f"DELETE & BLOCK complete for {jid}: blocked, removed, history deleted")

        except Exception as e:
            logger.error(f"Failed to delete & block contact: {e}")
            QMessageBox.critical(self, "Error", f"Failed to delete & block contact:\n{e}")

    def _on_view_muc_details(self, account_id: int, room_jid: str):
        """Delegate to DialogManager."""
        self.dialog_manager.show_muc_details_dialog(account_id, room_jid)

    def leave_muc(self, account_id: int, room_jid: str):
        """
        Leave a MUC room (centralized handler for all leave operations).

        Handles:
        - User confirmation
        - Sending XMPP leave
        - Removing bookmark from server
        - Removing bookmark from database
        - Updating UI (contact list, chat view)

        Args:
            account_id: Account ID
            room_jid: Room JID
        """
        logger.debug(f"Leave MUC requested: {room_jid}")

        # Check if account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot leave room while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Get room name for confirmation dialog
        room_info = self.db.fetchone("""
            SELECT b.name FROM bookmark b
            JOIN jid j ON b.jid_id = j.id
            WHERE b.account_id = ? AND j.bare_jid = ?
        """, (account_id, room_jid))

        room_name = room_info['name'] if (room_info and room_info['name']) else room_jid

        # Confirm leaving
        reply = QMessageBox.question(
            self,
            "Leave Room",
            f"Leave room '{room_name}'?\n\n"
            f"This will remove it from your bookmarks.\n"
            f"Message history will be preserved.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            return

        try:
            # Leave room via XMPP
            account.client.leave_room(room_jid)
            logger.debug(f"Sent leave room request for {room_jid}")

            # Remove bookmark from server (XEP-0402)
            asyncio.create_task(account.client.remove_bookmark(room_jid))
            logger.debug(f"Syncing bookmark removal to server: {room_jid}")

            # Remove bookmark and roster entry from local database
            # (Some clients add MUCs to server roster, so clean both tables)
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (room_jid,))
            if jid_row:
                jid_id = jid_row['id']

                # Delete from bookmark table
                self.db.execute("DELETE FROM bookmark WHERE account_id = ? AND jid_id = ?",
                               (account_id, jid_id))

                # Delete from roster table (if present)
                self.db.execute("DELETE FROM roster WHERE account_id = ? AND jid_id = ?",
                               (account_id, jid_id))

                self.db.commit()
                logger.debug(f"Removed MUC from bookmark and roster tables: {room_jid}")

            # Refresh contact list to remove MUC entry
            self.contact_list.refresh()

            # Close chat view if currently viewing this room
            if self.chat_view.current_account_id == account_id and self.chat_view.current_jid == room_jid:
                self.chat_view.clear()

            # Log to both main logger and account-specific app logger
            logger.info(f"Left room {room_jid} and removed bookmark")
            if account.app_logger:
                account.app_logger.info(f"Left room '{room_name}' ({room_jid})")

        except Exception as e:
            logger.error(f"Failed to leave room: {e}")
            import traceback
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "Error", f"Failed to leave room:\n{e}")

    def _on_account_connect(self, account_id: int):
        """Handle Connect from account context menu."""
        logger.debug(f"Connect requested for account {account_id}")

        account = self.account_manager.get_account(account_id)
        if not account:
            QMessageBox.warning(self, "Error", f"Account {account_id} not found")
            return

        if account.is_connected():
            logger.warning(f"Account {account_id} is already connected")
            return

        try:
            account.connect()
            # Refresh after a short delay to allow connection event to complete
            QTimer.singleShot(1000, self.contact_list.refresh)
            logger.debug(f"Account {account_id} connecting...")
        except Exception as e:
            logger.error(f"Failed to connect account {account_id}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to connect:\n{e}")

    def _on_account_disconnect(self, account_id: int):
        """Handle Disconnect from account context menu."""
        logger.debug(f"Disconnect requested for account {account_id}")

        account = self.account_manager.get_account(account_id)
        if not account:
            QMessageBox.warning(self, "Error", f"Account {account_id} not found")
            return

        if not account.is_connected():
            logger.warning(f"Account {account_id} is already disconnected")
            return

        try:
            account.disconnect()
            # Refresh after a short delay to allow disconnection event to complete
            QTimer.singleShot(500, self.contact_list.refresh)
            logger.debug(f"Account {account_id} disconnect initiated")
        except Exception as e:
            logger.error(f"Failed to disconnect account {account_id}: {e}")
            QMessageBox.critical(self, "Error", f"Failed to disconnect:\n{e}")

    def _on_add_contact_for_account(self, account_id: int):
        """Handle Add Contact for specific account from context menu."""
        logger.debug(f"Add Contact requested for account {account_id}")

        # Check if selected account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot add contact while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Open contact dialog with pre-selected account
        dialog = ContactDialog(account_id=account_id, parent=self)
        dialog.contact_saved.connect(self._on_contact_saved)
        if dialog.exec() == QDialog.Accepted:
            logger.debug("Contact saved successfully")

    def _on_join_room_for_account(self, account_id: int):
        """Handle Add Group for specific account from context menu."""
        logger.debug(f"Add Group requested for account {account_id}")

        # Check if selected account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self,
                "Cannot Perform Operation",
                f"Cannot add group while offline.\n\n"
                f"Please connect the account first."
            )
            return

        # Open join room dialog with pre-selected account
        dialog = JoinRoomDialog(account_id=account_id, parent=self)
        if dialog.exec() == QDialog.Accepted:
            # Get joined room info
            room_jid = dialog.room_jid
            nick = dialog.nick
            password = dialog.password if dialog.password else None

            logger.debug(f"Joining room: {room_jid} as {nick}")

            # Add room to client configuration and join
            if account and account.client:
                asyncio.create_task(account.add_and_join_room(room_jid, nick, password))
                logger.debug(f"Room join initiated: {room_jid}")

                # Refresh contact list to show new room
                self.contact_list.load_roster()
            else:
                QMessageBox.warning(self, "Error", "Account not connected.")

    @Slot(int)
    @Slot(int, str)
    def _on_connection_state_changed(self, account_id: int, state: str):
        """
        Handle connection state change signal from account.

        Args:
            account_id: Account ID whose connection state changed
            state: New connection state ('connecting'|'connected'|'disconnected'|'error')
        """
        logger.info(f"Connection state changed for account {account_id}: {state}")
        # Refresh contact list to update account connection indicator
        self.contact_list.refresh()
        # Update status bar to reflect new connection state
        self._update_status_bar_stats()

    def _on_roster_updated(self, account_id: int):
        """
        Handle roster update signal from account.

        Args:
            account_id: Account ID whose roster was updated
        """
        logger.debug(f"Roster updated for account {account_id}, refreshing contact list")
        self.contact_list.refresh()

        # If the currently open chat is from this account, update its header display name
        if self.chat_view.current_account_id == account_id and self.chat_view.current_jid:
            jid = self.chat_view.current_jid
            logger.debug(f"Updating chat header display name for open chat: {jid}")
            # Use unified display name refresh (applies 3-source priority)
            self._refresh_contact_display_name(account_id, jid)

    @Slot(int, str, bool)
    def _on_message_received(self, account_id: int, from_jid: str, is_marker: bool = False):
        """
        Handle incoming message signal from account.

        Args:
            account_id: Account ID
            from_jid: Sender JID
            is_marker: True if marker/receipt update, False if actual new message
        """
        event_type = "marker/receipt" if is_marker else "message"
        logger.debug(f"{event_type.capitalize()} received from {from_jid} on account {account_id}")

        # Check if this message is for the currently open chat
        is_current_chat = (self.chat_view.current_account_id == account_id and
                          self.chat_view.current_jid == from_jid)

        if is_current_chat:
            # Refresh the chat view
            # Only send markers for actual new messages, not for marker/receipt updates
            self.chat_view.refresh(send_markers=(not is_marker))
            logger.debug(f"Chat view refreshed for {event_type}")

        # Check if this is a new conversation (not currently in chat list)
        # Only refresh roster for new conversations to avoid expensive reloads
        if not is_marker:
            item = self.contact_list._find_contact_item(account_id, from_jid)
            if item is None:
                # New conversation - contact not in chat list yet
                logger.debug(f"New conversation from {from_jid}, refreshing chat list")
                self.contact_list.load_roster()

        # Update unread indicators in contact list (always, even if chat is open)
        self.contact_list.update_unread_indicators(account_id, from_jid)

        # Update status bar stats for actual new messages (not marker/receipt updates)
        if not is_marker:
            self._update_status_bar_stats()

        # Send OS notification for actual new messages (not if chat is open or if it's a marker)
        if not is_marker and not is_current_chat:
            self.notification_manager.send_message_notification(account_id, from_jid)

    def _on_chat_state_changed(self, account_id: int, from_jid: str, state: str):
        """
        Handle chat state change (typing indicators).

        Args:
            account_id: Account ID
            from_jid: Contact JID
            state: Chat state ('active', 'composing', 'paused', 'inactive', 'gone')
        """
        logger.debug(f"Chat state from {from_jid}: {state}")

        # Update typing indicator in contact list
        self.contact_list.update_typing_indicator(account_id, from_jid, state)

        # Also update typing indicator in chat header if this is the current chat
        if (self.chat_view.current_account_id == account_id and
            self.chat_view.current_jid == from_jid):
            self.chat_view.update_typing_indicator(state)

    def _on_presence_changed(self, account_id: int, jid: str, presence: str):
        """
        Handle presence change (contact status updates).

        Args:
            account_id: Account ID
            jid: Contact JID
            presence: Presence show value ('available', 'away', 'xa', 'dnd', 'unavailable')
        """
        logger.debug(f"Presence change for {jid}: {presence}")

        # Update presence indicator in contact list (event-driven, not polling!)
        self.contact_list.update_presence_single(account_id, jid, presence)

    def _refresh_contact_display_name(self, account_id: int, jid: str):
        """
        Unified method to refresh display name for a contact.

        Applies 3-source priority: roster.name → nickname → JID
        Updates contact list and chat header if applicable.

        Args:
            account_id: Account ID
            jid: Contact bare JID
        """
        # Get account
        account = self.account_manager.get_account(account_id)
        if not account:
            return

        # Get roster name (highest priority)
        roster_name = None
        if account.client:
            roster = account.client.client_roster
            if jid in roster:
                try:
                    roster_name = roster[jid]['name'] or None
                except (KeyError, TypeError):
                    pass

        # Get display name using 3-source priority
        display_name = account.get_contact_display_name(jid, roster_name=roster_name)

        # Refresh contact list (for now, reload entire roster - can optimize later)
        self.contact_list.load_roster()

        # If this chat is open, update header
        if (self.chat_view.current_account_id == account_id and
            self.chat_view.current_jid == jid):
            logger.debug(f"Updating chat header display name for open chat: {jid}")
            base_name = f"💬 {display_name}"
            self.chat_view.header.update_display_name(base_name)
            self.chat_view.header.roster_name = roster_name

    @Slot(int, str)
    def _on_nickname_updated(self, account_id: int, jid: str, nickname: str):
        """
        Handle nickname update signal from account (XEP-0172).

        Args:
            account_id: Account ID
            jid: JID whose nickname was updated
            nickname: New nickname (empty string if cleared)
        """
        logger.debug(f"Nickname updated for {jid} on account {account_id}: {nickname if nickname else '(cleared)'}")
        # Use unified display name refresh
        self._refresh_contact_display_name(account_id, jid)

    def _on_avatar_updated(self, account_id: int, jid: str):
        """
        Handle avatar update signal from account.

        Args:
            account_id: Account ID
            jid: JID whose avatar was updated
        """
        logger.debug(f"Avatar updated for {jid} on account {account_id}")

        # If this is the currently open chat, refresh the avatar
        if (self.chat_view.current_account_id == account_id and
            self.chat_view.current_jid == jid):
            logger.debug(f"Refreshing avatar for current chat: {jid}")
            # Invalidate cache for this JID
            from ..utils.avatar import get_avatar_cache
            get_avatar_cache().invalidate(jid)
            # Refresh avatar display in header
            self.chat_view.header._update_avatar()

    def _on_muc_invite_received(self, account_id: int, room_jid: str, inviter_jid: str, reason: str, password: str):
        """
        Handle MUC invitation.

        Args:
            account_id: Account ID
            room_jid: MUC room JID
            inviter_jid: JID of person who sent the invite
            reason: Invitation reason (may be empty)
            password: Room password (may be empty)
        """
        logger.info(f"MUC invite received: {room_jid} from {inviter_jid} (account {account_id})")

        # Extract room name from JID localpart (before @)
        room_name = room_jid.split('@')[0] if '@' in room_jid else room_jid

        # Build invitation message
        invite_msg = f"{inviter_jid} invited you to join:\n\n{room_name} ({room_jid})"
        if reason:
            invite_msg += f"\n\nReason: {reason}"
        if password:
            invite_msg += f"\n\n(Room is password protected)"

        # Show dialog
        reply = QMessageBox.question(
            self,
            "MUC Invitation",
            invite_msg + "\n\nDo you want to join this room?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            # Get account
            account = self.account_manager.get_account(account_id)
            if not account:
                QMessageBox.warning(self, "Error", "Account not found.")
                return

            # Check if account is connected
            if not account.is_connected():
                QMessageBox.warning(
                    self,
                    "Cannot Add Group",
                    "Cannot add group while offline.\n\n"
                    "Please connect the account first."
                )
                return

            # Get account nickname for MUC (with fallbacks: muc_nickname > nickname > JID localpart)
            account_data = self.db.fetchone("SELECT muc_nickname, nickname, bare_jid FROM account WHERE id = ?", (account_id,))
            if account_data and account_data['muc_nickname']:
                nick = account_data['muc_nickname']
            elif account_data and account_data['nickname']:
                nick = account_data['nickname']
            elif account_data and account_data['bare_jid']:
                # Fallback: use localpart of JID
                nick = account_data['bare_jid'].split('@')[0]
            else:
                nick = 'User'

            # Save bookmark and trigger join (all sync, delegate async work)
            try:
                # Get or create JID entry
                jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (room_jid,))
                if jid_row:
                    jid_id = jid_row['id']
                else:
                    cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (room_jid,))
                    jid_id = cursor.lastrowid

                # Store bookmark locally (use JID as name for now, will be updated after join)
                encoded_password = base64.b64encode(password.encode()).decode() if password else None
                self.db.execute("""
                    INSERT INTO bookmark (account_id, jid_id, name, nick, password, autojoin)
                    VALUES (?, ?, ?, ?, ?, 1)
                    ON CONFLICT (account_id, jid_id) DO UPDATE SET
                        name = excluded.name,
                        nick = excluded.nick,
                        password = excluded.password,
                        autojoin = excluded.autojoin
                """, (account_id, jid_id, room_jid, nick, encoded_password))
                self.db.commit()
                logger.debug(f"Bookmark saved for {room_jid}")

                # Refresh roster to show new bookmark
                self.contact_list.load_roster()

                # Defer async operations to escape XMPP callback context
                # Using QTimer.singleShot(0) to queue for next event loop iteration
                QTimer.singleShot(0, lambda: self._execute_room_join_from_invite(
                    account_id, room_jid, nick, password
                ))
                logger.debug(f"Queued room join for next event loop: {room_jid}")

            except Exception as e:
                logger.error(f"Failed to save bookmark: {e}")
                QMessageBox.critical(self, "Error", f"Failed to join room: {e}")

    def _execute_room_join_from_invite(self, account_id: int, room_jid: str, nick: str, password: str):
        """
        Execute room join operations after escaping XMPP callback context.
        Called via QTimer.singleShot(0) to defer to next event loop iteration.

        Args:
            account_id: Account ID
            room_jid: MUC room JID
            nick: Nickname to use
            password: Room password (may be empty string)
        """
        logger.debug(f"Executing deferred room join: {room_jid}")

        # Get account
        account = self.account_manager.get_account(account_id)
        if not account or not account.client:
            logger.error(f"Cannot join room - account {account_id} not available")
            QMessageBox.warning(self, "Error", "Account not available.")
            return

        # Check if still connected
        if not account.is_connected():
            logger.error(f"Cannot join room - account {account_id} disconnected")
            QMessageBox.warning(self, "Error", "Account disconnected. Room will auto-join on next connection.")
            return

        try:
            # Sync bookmark to server (XEP-0402)
            asyncio.create_task(
                account.client.add_bookmark(
                    jid=room_jid,
                    name=room_jid,  # Will be updated via disco#info after join
                    nick=nick,
                    password=password,
                    autojoin=True
                )
            )
            logger.debug(f"Syncing bookmark to server: {room_jid}")

            # Join the room immediately
            asyncio.create_task(account.add_and_join_room(room_jid, nick, password))
            logger.debug(f"Joining room from invite: {room_jid}")

        except Exception as e:
            logger.error(f"Failed to join room: {e}")
            import traceback
            logger.error(traceback.format_exc())
            QMessageBox.critical(self, "Error", f"Failed to join room: {e}")

    def _on_muc_role_changed(self, account_id: int, room_jid: str, old_role: str, new_role: str):
        """
        Handle MUC role change (e.g., visitor → participant when voice granted).

        Updates UI if currently viewing this room.

        Args:
            account_id: Account ID
            room_jid: Room JID where role changed
            old_role: Previous role
            new_role: New role
        """
        logger.info(f"MUC role changed in {room_jid}: {old_role} → {new_role}")

        # If this is the currently open chat, update input state
        if (self.chat_view.current_account_id == account_id and
            self.chat_view.current_jid == room_jid and
            self.chat_view.current_is_muc):
            logger.debug(f"Updating input state for current room: {room_jid}")
            self.chat_view._update_muc_input_state(account_id, room_jid)

    def _on_manage_subscription(self, account_id: int, jid: str, roster_id: int):
        """Delegate to SubscriptionManager."""
        self.subscription_manager.on_manage_subscription(account_id, jid, roster_id)

    def _apply_block_status(self, account_id: int, jid: str, should_block: bool):
        """Delegate to SubscriptionManager."""
        self.subscription_manager.apply_block_status(account_id, jid, should_block)

    def _on_block_status_changed(self, account_id: int, jid: str, is_blocked: bool):
        """Delegate to SubscriptionManager."""
        self.subscription_manager.on_block_status_changed(account_id, jid, is_blocked)

    def _update_subscription(self, account_id: int, jid: str, can_see_theirs: bool, they_can_see_ours: bool):
        """Delegate to SubscriptionManager."""
        return self.subscription_manager.update_subscription(account_id, jid, can_see_theirs, they_can_see_ours)

    def request_call_stats(self, account_id: int, session_id: str):
        """
        Request call statistics update for a session.

        Called by CallWindow every 2 seconds to update tech details.

        Args:
            account_id: Account ID
            session_id: Jingle session ID
        """
        self.call_manager.request_call_stats(account_id, session_id)

    # =========================================================================
    # Other Signal Handlers
    # =========================================================================

    def _update_chat_receipts(self):
        """Poll and update receipt indicators in chat view."""
        # Only refresh if a chat is open AND the account still exists
        if self.chat_view.current_account_id and self.chat_view.current_jid:
            # Check if account still exists (could have been deleted)
            if self.account_manager.get_account(self.chat_view.current_account_id):
                self.chat_view.refresh(send_markers=False)  # Just update UI, don't send markers

    def set_chat_polling_enabled(self, enabled: bool):
        """
        Enable/disable chat polling timer based on scroll zone.

        Called by MessageDisplayWidget when user scrolls between live and history zones.
        Live zone (>50% scroll) = enable polling for real-time updates.
        History zone (<=50% scroll) = disable polling for better performance.

        Args:
            enabled: True to enable polling (live zone), False to disable (history zone)
        """
        if enabled:
            if not self.receipt_timer.isActive():
                self.receipt_timer.start(2000)
                logger.debug("Chat polling ENABLED (live zone - bottom 50%)")
        else:
            if self.receipt_timer.isActive():
                self.receipt_timer.stop()
                logger.debug("Chat polling DISABLED (history zone - top 50%)")

    @Slot(int, str, str, bool)

    def closeEvent(self, event):
        """Handle window close event - cleanup all services."""
        logger.debug("Main window closing...")

        # Stop status bar timer
        if hasattr(self, 'status_bar_timer'):
            self.status_bar_timer.stop()

        # Step 1: Disconnect all XMPP accounts (fire and forget)
        try:
            logger.debug("Disconnecting XMPP accounts...")
            self.account_manager.disconnect_all()
            logger.debug("XMPP disconnect initiated")
        except Exception as e:
            logger.error(f"Error disconnecting XMPP accounts: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # Step 2: Stop Go call service via CallManager
        self.call_manager.shutdown_service(signal_shutdown=self._signal_shutdown)

        # Accept close event
        event.accept()
