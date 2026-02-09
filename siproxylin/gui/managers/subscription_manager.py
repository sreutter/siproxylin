"""
SubscriptionManager - Manages presence subscriptions and contact blocking.

Extracted from MainWindow to improve maintainability.
"""

import logging
import asyncio
from PySide6.QtWidgets import QMessageBox, QDialog
from PySide6.QtCore import Qt, QTimer


logger = logging.getLogger('siproxylin.subscription_manager')


class SubscriptionManager:
    """
    Manages presence subscriptions and blocking functionality.

    Responsibilities:
    - Handle subscription dialogs (request, approve, deny, revoke)
    - Manage contact blocking/unblocking (XEP-0191)
    - Update subscription states in database and UI
    - Connect subscription signals from accounts
    """

    def __init__(self, main_window):
        """
        Initialize SubscriptionManager.

        Args:
            main_window: MainWindow instance (for accessing widgets and services)
        """
        self.main_window = main_window
        self.account_manager = main_window.account_manager
        self.db = main_window.db
        self.contact_list = main_window.contact_list
        self.chat_view = main_window.chat_view

        logger.debug("SubscriptionManager initialized")

    def connect_account_signals(self, account):
        """
        Connect subscription-related signals from an account.

        Args:
            account: XMPPAccount instance
        """
        account.subscription_request_received.connect(self.on_subscription_request_received)
        account.subscription_changed.connect(self.on_subscription_changed)
        logger.debug(f"Connected subscription signals for account {account.account_id}")

    def on_manage_subscription(self, account_id: int, jid: str, roster_id: int):
        """
        Handle subscription management request from context menu.

        Args:
            account_id: Account ID
            jid: Contact JID
            roster_id: Roster entry ID
        """
        logger.debug(f"Opening subscription management dialog for {jid}")

        # Import here to avoid circular dependency
        from ..dialogs.subscription_dialog import SubscriptionDialog

        # Show subscription dialog
        dialog = SubscriptionDialog(account_id, jid, roster_id, parent=self.main_window)
        dialog.subscription_changed.connect(self.on_subscription_dialog_changed)
        dialog.setAttribute(Qt.WA_DeleteOnClose)
        dialog.show()

    def apply_block_status(self, account_id: int, jid: str, should_block: bool):
        """
        Unified method to block/unblock a contact.
        Used by both context menu and ContactDetailsDialog.

        Args:
            account_id: Account ID
            jid: Contact JID
            should_block: True to block, False to unblock
        """
        action = "block" if should_block else "unblock"
        logger.debug(f"Applying {action} for {jid}")

        # Send XEP-0191 IQ to server
        account = self.account_manager.get_account(account_id)
        if account and account.is_connected():
            try:
                if should_block:
                    asyncio.create_task(account.client.block_contact(jid))
                else:
                    asyncio.create_task(account.client.unblock_contact(jid))
                logger.debug(f"Sent {action} IQ for {jid}")
            except Exception as e:
                logger.error(f"Failed to send {action} IQ: {e}")

        # Update database
        self.db.execute("""
            UPDATE roster SET blocked = ?
            WHERE account_id = ? AND jid_id = (SELECT id FROM jid WHERE bare_jid = ?)
        """, (1 if should_block else 0, account_id, jid))
        self.db.commit()

        # If this contact's chat is currently open, update its UI state
        if self.chat_view.current_account_id == account_id and self.chat_view.current_jid == jid:
            self.chat_view.update_blocked_status(should_block)
            logger.debug(f"Updated chat view blocked status for {jid}")

        # Refresh contact list to update blocked indicator
        self.contact_list.refresh()

    def on_block_status_changed(self, account_id: int, jid: str, is_blocked: bool):
        """
        Handle block status change from ContactDetailsDialog.
        Delegates to unified apply_block_status() method.

        Args:
            account_id: Account ID
            jid: Contact JID
            is_blocked: New blocked status
        """
        self.apply_block_status(account_id, jid, is_blocked)

    def update_subscription(self, account_id: int, jid: str, can_see_theirs: bool, they_can_see_ours: bool):
        """
        Update presence subscription for a contact (shared method for both dialogs).

        Args:
            account_id: Account ID
            jid: Contact JID
            can_see_theirs: Whether we want to see their presence
            they_can_see_ours: Whether they can see our presence

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug(f"Updating subscription for {jid}: see_theirs={can_see_theirs}, they_see_ours={they_can_see_ours}")

        # Get account
        account = self.account_manager.get_account(account_id)
        if not account:
            QMessageBox.warning(self.main_window, "Error", "Account not found.")
            return False

        # Check connection
        if not account.is_connected():
            QMessageBox.warning(
                self.main_window,
                "Cannot Update Subscription",
                "Cannot update subscription while offline.\n\nPlease connect the account first."
            )
            return False

        # Get current subscription state from boolean fields
        roster_row = self.db.fetchone(
            "SELECT we_see_their_presence, they_see_our_presence FROM roster WHERE account_id = ? AND jid_id = (SELECT id FROM jid WHERE bare_jid = ?)",
            (account_id, jid)
        )
        current_can_see = bool(roster_row['we_see_their_presence']) if roster_row else False
        current_they_see = bool(roster_row['they_see_our_presence']) if roster_row else False

        try:
            # Handle changes for "I can see their presence"
            if can_see_theirs and not current_can_see:
                # Send subscribe request
                asyncio.create_task(account.request_subscription(jid))
                logger.debug(f"Sent subscription request to {jid}")
            elif not can_see_theirs and current_can_see:
                # Cancel our subscription
                asyncio.create_task(account.cancel_subscription(jid))
                logger.debug(f"Cancelled subscription to {jid}")

            # Handle changes for "They can see my presence"
            if they_can_see_ours and not current_they_see:
                # Send subscription approval/pre-approval (RFC 6121 §3.4)
                asyncio.create_task(account.approve_subscription(jid))
                logger.debug(f"Sent subscription approval/pre-approval for {jid}")
            elif not they_can_see_ours and current_they_see:
                # Revoke their subscription
                asyncio.create_task(account.revoke_subscription(jid))
                logger.debug(f"Revoked subscription for {jid}")

            return True

        except Exception as e:
            logger.error(f"Failed to update subscription: {e}")
            QMessageBox.critical(self.main_window, "Error", f"Failed to update subscription: {e}")
            return False

    def on_subscription_dialog_changed(self, account_id: int, jid: str, can_see_theirs: bool, they_can_see_ours: bool):
        """
        Handle subscription changes from SubscriptionDialog.

        Args:
            account_id: Account ID
            jid: Contact JID
            can_see_theirs: Whether we want to see their presence
            they_can_see_ours: Whether they can see our presence
        """
        self.update_subscription(account_id, jid, can_see_theirs, they_can_see_ours)

    def on_subscription_request_received(self, account_id: int, from_jid: str):
        """
        Handle incoming subscription request.

        Args:
            account_id: Account ID
            from_jid: JID requesting subscription
        """
        logger.info(f"Subscription request from {from_jid} on account {account_id}")

        # Defer dialog to avoid asyncio reentrancy issues (same as MUC invites)
        def show_dialog():
            # Import here to avoid circular dependency
            from ..dialogs.subscription_request_dialog import SubscriptionRequestDialog

            # Show approval dialog
            dialog = SubscriptionRequestDialog(from_jid, parent=self.main_window)
            result = dialog.exec()

            if result == QDialog.Accepted:
                # User approved
                also_request = dialog.also_request

                # Get account
                account = self.account_manager.get_account(account_id)
                if not account:
                    logger.error(f"Account {account_id} not found")
                    return

                # Check connection
                if not account.is_connected():
                    logger.warning(f"Account {account_id} not connected, cannot approve subscription")
                    return

                try:
                    # Approve their request
                    asyncio.create_task(account.approve_subscription(from_jid))
                    logger.debug(f"Approved subscription request from {from_jid}")

                    # Also request their subscription if checkbox was checked
                    if also_request:
                        asyncio.create_task(account.request_subscription(from_jid))
                        logger.debug(f"Also requested subscription from {from_jid} (mutual)")

                except Exception as e:
                    logger.error(f"Failed to handle subscription request: {e}")
            else:
                # User denied
                logger.debug(f"User denied subscription request from {from_jid}")

                # Get account
                account = self.account_manager.get_account(account_id)
                if account and account.is_connected():
                    try:
                        asyncio.create_task(account.deny_subscription(from_jid))
                        logger.debug(f"Sent denial to {from_jid}")
                    except Exception as e:
                        logger.error(f"Failed to deny subscription: {e}")

        # Defer to next event loop iteration
        QTimer.singleShot(0, show_dialog)

    def on_subscription_changed(self, account_id: int, from_jid: str, change_type: str):
        """
        Handle subscription state change notification.

        Args:
            account_id: Account ID
            from_jid: JID whose subscription changed
            change_type: Type of change
        """
        logger.debug(f"Subscription changed for {from_jid}: {change_type}")
        # Roster is already refreshed by roster_updated signal, nothing more to do
