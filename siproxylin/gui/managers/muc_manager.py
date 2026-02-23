"""
MUCManager - Manages MUC (Multi-User Chat) operations.

Extracted from MainWindow to improve maintainability.
"""

import logging
import asyncio
import base64
from PySide6.QtWidgets import QMessageBox


logger = logging.getLogger('siproxylin.muc_manager')


class MUCManager:
    """
    Manages MUC (Multi-User Chat) operations.

    Responsibilities:
    - Handle MUC invitations and room joins
    - Handle MUC role changes
    - Leave MUC rooms with cleanup
    - Connect MUC signals from accounts
    """

    def __init__(self, main_window):
        """
        Initialize MUCManager.

        Args:
            main_window: MainWindow instance (for accessing widgets and services)
        """
        self.main_window = main_window
        self.account_manager = main_window.account_manager
        self.contact_list = main_window.contact_list
        self.chat_view = main_window.chat_view
        self.db = main_window.db

        logger.debug("MUCManager initialized")

    def connect_account_signals(self, account):
        """
        Connect MUC-related signals from an account.

        Args:
            account: XMPPAccount instance
        """
        account.muc_invite_received.connect(self.on_muc_invite_received)
        account.muc_role_changed.connect(self.on_muc_role_changed)
        logger.debug(f"Connected MUC signals for account {account.account_id}")

    def on_muc_invite_received(self, account_id: int, room_jid: str, inviter_jid: str, reason: str, password: str):
        """
        Handle MUC invitation.

        Creates a bookmark with autojoin=0 so the invite appears in the roster
        as a joinable MUC. User can join via "Join Group" button in chat header.

        Args:
            account_id: Account ID
            room_jid: MUC room JID
            inviter_jid: JID of person who sent the invite
            reason: Invitation reason (may be empty)
            password: Room password (may be empty)
        """
        logger.info(f"MUC invite received: {room_jid} from {inviter_jid} (account {account_id})")

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

        try:
            # Get or create JID entry
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (room_jid,))
            if jid_row:
                jid_id = jid_row['id']
            else:
                cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (room_jid,))
                jid_id = cursor.lastrowid

            # Store bookmark with autojoin=0 (user can join manually via UI)
            # Use room JID as name for now, will be updated via disco#info when joined
            encoded_password = base64.b64encode(password.encode()).decode() if password else None
            self.db.execute("""
                INSERT INTO bookmark (account_id, jid_id, name, nick, password, autojoin)
                VALUES (?, ?, ?, ?, ?, 0)
                ON CONFLICT (account_id, jid_id) DO UPDATE SET
                    name = excluded.name,
                    nick = excluded.nick,
                    password = excluded.password
            """, (account_id, jid_id, room_jid, nick, encoded_password))
            self.db.commit()
            logger.info(f"Saved invite as bookmark (autojoin=0): {room_jid}")

            # Refresh roster to show new bookmark
            self.contact_list.load_roster()

        except Exception as e:
            logger.error(f"Failed to save MUC invite bookmark: {e}")
            import traceback
            logger.error(traceback.format_exc())

    def on_muc_role_changed(self, account_id: int, room_jid: str, old_role: str, new_role: str):
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

    def invite_to_muc(self, account_id: int, room_jid: str):
        """
        Invite a contact to a MUC room.

        Shows a dialog to enter the invitee's JID and optional reason,
        then sends the invitation via XMPP.

        Args:
            account_id: Account ID
            room_jid: Room JID to invite to
        """
        from ..dialogs import InviteContactDialog

        logger.info(f"Invite to MUC requested: {room_jid} (account {account_id})")

        # Check if account is connected
        account = self.account_manager.get_account(account_id)
        if not account or not account.is_connected():
            QMessageBox.warning(
                self.main_window,
                "Cannot Send Invite",
                "Cannot send invitation while offline.\n\n"
                "Please connect the account first."
            )
            return

        # Show invite dialog
        dialog = InviteContactDialog(self.main_window, room_jid)
        if dialog.exec():
            invite_data = dialog.get_invite_data()
            if invite_data:
                invitee_jid, reason = invite_data
                logger.info(f"Sending invite: {invitee_jid} to {room_jid}")

                # Send invite via MucBarrel
                try:
                    account.muc.invite_to_room(room_jid, invitee_jid, reason)
                    logger.info(f"Invite sent successfully to {invitee_jid}")
                except Exception as e:
                    logger.error(f"Failed to send invite: {e}")
                    QMessageBox.critical(
                        self.main_window,
                        "Invite Failed",
                        f"Failed to send invitation:\n\n{e}"
                    )

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
                self.main_window,
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
            self.main_window,
            "Leave Room",
            f"Leave room '{room_name}'?\n\n"
            f"This will permanently delete all messages and remove the room.\n"
            f"This action cannot be undone.",
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

                # Delete conversation (CASCADE will delete all content_items/messages)
                self.db.execute("DELETE FROM conversation WHERE account_id = ? AND jid_id = ? AND type = 1",
                               (account_id, jid_id))

                self.db.commit()
                logger.debug(f"Removed MUC bookmark, roster, and conversation (with all messages): {room_jid}")

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
            QMessageBox.critical(self.main_window, "Error", f"Failed to leave room:\n{e}")
