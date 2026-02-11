"""
Message Reactions Handler (XEP-0444)

Handles both incoming and outgoing message reactions.
Extracted from MessageBarrel to keep file sizes manageable.
"""

import logging
import time
from typing import Optional
from slixmpp.jid import JID


class MessageReactions:
    """Handles message reaction logic for both incoming and outgoing reactions."""

    def __init__(self, message_barrel):
        """
        Initialize reactions handler.

        Args:
            message_barrel: Parent MessageBarrel instance (to access client, db, logger, account_id)
        """
        self.barrel = message_barrel

    @property
    def account_id(self):
        """Get account_id from parent barrel."""
        return self.barrel.account_id

    @property
    def client(self):
        """Get client from parent barrel (dynamic reference)."""
        return self.barrel.client

    @property
    def db(self):
        """Get db from parent barrel."""
        return self.barrel.db

    @property
    def logger(self):
        """Get logger from parent barrel."""
        return self.barrel.logger

    def send_reaction(self, to_jid: str, message_id: str, emoji: str):
        """
        Send a reaction to a message.

        Args:
            to_jid: Recipient JID
            message_id: Message ID to react to
            emoji: Emoji reaction
        """
        if not self.client:
            raise RuntimeError("Not connected")

        # Send via XMPP
        self.client.send_reaction(to_jid, message_id, emoji)

        # Store locally for immediate feedback (optimistic UI)
        self._store_sent_reaction(message_id, emoji)

        if self.logger:
            self.logger.info(f"Sent reaction {emoji} to {to_jid} message {message_id}")

    def remove_reaction(self, to_jid: str, message_id: str):
        """
        Remove all reactions from a message.

        Args:
            to_jid: Recipient JID
            message_id: Message ID
        """
        if not self.client:
            raise RuntimeError("Not connected")

        # Send via XMPP
        self.client.remove_reaction(to_jid, message_id)

        # Remove locally for immediate feedback
        self._store_sent_reaction(message_id, None)

        if self.logger:
            self.logger.info(f"Removed reactions from {to_jid} message {message_id}")

    def handle_incoming_reaction(self, metadata, message_id: str, emojis: list):
        """
        Handle incoming reaction (XEP-0444).
        Stores reaction in database.

        For MUC: Uses occupant_id table to track nickname → occupant_id mapping
        For 1-1: Uses jid_id as before

        Args:
            metadata: MessageMetadata with reaction sender info
            message_id: ID of message being reacted to (origin_id/stanza_id/message_id)
            emojis: List of emoji strings (empty if reactions removed)
        """
        # Determine display name for logging
        if metadata.message_type == 'groupchat':
            display_from = metadata.muc_nick or metadata.from_jid
        else:
            display_from = JID(metadata.from_jid).bare

        if self.logger:
            if emojis:
                self.logger.info(f"Reaction from {display_from} to {message_id}: {', '.join(emojis)}")
            else:
                self.logger.info(f"Reactions removed from {display_from} on {message_id}")

        try:
            # Find the content_item by message_id
            content_item = self._find_content_item(message_id)

            if not content_item:
                if self.logger:
                    self.logger.warning(f"Reaction: Message {message_id} not found")
                return

            content_item_id = content_item['id']
            conv_type = content_item['conv_type']  # 0=chat, 1=groupchat
            reaction_time = int(time.time() * 1000)  # milliseconds
            emojis_str = ','.join(emojis) if emojis else None

            # Handle MUC vs 1-1 reactions differently
            if conv_type == 1:  # MUC
                self._handle_muc_reaction(
                    content_item, content_item_id, metadata,
                    emojis, emojis_str, reaction_time
                )
            else:  # 1-1 chat
                self._handle_chat_reaction(
                    content_item_id, metadata,
                    emojis, emojis_str, reaction_time
                )

            self.db.commit()

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to process reaction: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def _store_sent_reaction(self, message_id: str, emoji: Optional[str]):
        """
        Store a sent reaction locally for immediate feedback.

        This provides optimistic UI updates for our own reactions.

        Args:
            message_id: Message ID to react to
            emoji: Emoji string, or None to remove reactions
        """
        try:
            # Find content_item by message_id
            content_item = self._find_content_item(message_id)

            if not content_item:
                if self.logger:
                    self.logger.warning(f"Could not find message {message_id} to store reaction")
                return

            content_item_id = content_item['id']
            conv_type = content_item['conv_type']  # 0=chat, 1=groupchat
            reaction_time = int(time.time() * 1000)

            # Handle MUC vs 1-1 reactions - use occupant_id for MUC, jid_id for 1-1
            if conv_type == 1:  # MUC
                self._store_sent_muc_reaction(content_item, content_item_id, emoji, reaction_time)
            else:  # 1-1 chat
                self._store_sent_chat_reaction(content_item_id, emoji, reaction_time)

            self.db.commit()
            if self.logger:
                self.logger.debug(f"Stored sent reaction locally: {emoji} on message {message_id}")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to store sent reaction: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def _find_content_item(self, message_id: str):
        """
        Find content_item by message_id.
        Searches both messages and file_transfers tables.

        Args:
            message_id: Message ID (origin_id, stanza_id, or message_id)

        Returns:
            Database row or None
        """
        return self.db.fetchone("""
            SELECT ci.id, ci.conversation_id, c.type as conv_type, c.jid_id as conv_jid_id, ci.time
            FROM content_item ci
            JOIN message m ON ci.foreign_id = m.id AND ci.content_type = 0
            JOIN conversation c ON ci.conversation_id = c.id
            WHERE m.account_id = ?
              AND (m.origin_id = ? OR m.stanza_id = ? OR m.message_id = ?)

            UNION

            SELECT ci.id, ci.conversation_id, c.type as conv_type, c.jid_id as conv_jid_id, ci.time
            FROM content_item ci
            JOIN file_transfer ft ON ci.foreign_id = ft.id AND ci.content_type = 2
            JOIN conversation c ON ci.conversation_id = c.id
            WHERE ft.account_id = ?
              AND (ft.origin_id = ? OR ft.stanza_id = ? OR ft.message_id = ?)

            ORDER BY ci.time DESC
            LIMIT 1
        """, (self.account_id, message_id, message_id, message_id,
              self.account_id, message_id, message_id, message_id))

    def _handle_muc_reaction(self, content_item, content_item_id, metadata,
                            emojis, emojis_str, reaction_time):
        """Handle incoming MUC reaction."""
        room_jid_id = content_item['conv_jid_id']
        nickname = metadata.muc_nick
        occupant_id_str = metadata.occupant_id

        if not nickname:
            if self.logger:
                self.logger.warning(f"MUC reaction without nickname")
            return

        # Upsert occupant (track nickname and occupant_id)
        self.db.execute("""
            INSERT INTO occupant (account_id, room_jid_id, nick, occupant_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(account_id, room_jid_id, nick)
            DO UPDATE SET occupant_id = COALESCE(excluded.occupant_id, occupant.occupant_id)
        """, (self.account_id, room_jid_id, nickname, occupant_id_str))

        # Get occupant.id
        occupant_row = self.db.fetchone("""
            SELECT id FROM occupant
            WHERE account_id = ? AND room_jid_id = ? AND nick = ?
        """, (self.account_id, room_jid_id, nickname))

        if not occupant_row:
            if self.logger:
                self.logger.error(f"Failed to get occupant.id for {nickname}")
            return

        occupant_db_id = occupant_row['id']

        if emojis:
            # Store MUC reaction using occupant_id
            self.db.execute("""
                INSERT INTO reaction (account_id, content_item_id, occupant_id, time, emojis)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, content_item_id, occupant_id)
                DO UPDATE SET emojis = excluded.emojis, time = excluded.time
            """, (self.account_id, content_item_id, occupant_db_id, reaction_time, emojis_str))
        else:
            # Remove MUC reaction
            self.db.execute("""
                DELETE FROM reaction
                WHERE account_id = ? AND content_item_id = ? AND occupant_id = ?
            """, (self.account_id, content_item_id, occupant_db_id))

    def _handle_chat_reaction(self, content_item_id, metadata, emojis, emojis_str, reaction_time):
        """Handle incoming 1-1 chat reaction."""
        # Get jid_id for sender
        from_bare_jid = JID(metadata.from_jid).bare
        jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (from_bare_jid,))
        if not jid_row:
            if self.logger:
                self.logger.warning(f"Reaction: JID {from_bare_jid} not found")
            return

        jid_id = jid_row['id']

        if emojis:
            # Store 1-1 reaction using jid_id
            self.db.execute("""
                INSERT INTO reaction (account_id, content_item_id, jid_id, time, emojis)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, content_item_id, jid_id)
                DO UPDATE SET emojis = excluded.emojis, time = excluded.time
            """, (self.account_id, content_item_id, jid_id, reaction_time, emojis_str))
        else:
            # Remove 1-1 reaction
            self.db.execute("""
                DELETE FROM reaction
                WHERE account_id = ? AND content_item_id = ? AND jid_id = ?
            """, (self.account_id, content_item_id, jid_id))

    def _store_sent_muc_reaction(self, content_item, content_item_id, emoji, reaction_time):
        """Store our own sent MUC reaction locally."""
        # Get conversation JID to lookup room
        conv_jid_row = self.db.fetchone("""
            SELECT c.jid_id, j.bare_jid
            FROM conversation c
            JOIN jid j ON c.jid_id = j.id
            WHERE c.id = ?
        """, (content_item['conversation_id'],))

        if not conv_jid_row:
            if self.logger:
                self.logger.error(f"Failed to get conversation JID")
            return

        room_jid_id = conv_jid_row['jid_id']
        room_jid = conv_jid_row['bare_jid']

        # Get our nickname in this room from client's rooms config
        if room_jid not in self.client.rooms:
            if self.logger:
                self.logger.error(f"Room {room_jid} not in client's rooms config")
            return

        our_nick = self.client.rooms[room_jid].get('nick')
        if not our_nick:
            if self.logger:
                self.logger.error(f"Failed to get our nickname in MUC {room_jid}")
            return

        # Get or create occupant entry
        self.db.execute("""
            INSERT INTO occupant (account_id, room_jid_id, nick)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, room_jid_id, nick) DO NOTHING
        """, (self.account_id, room_jid_id, our_nick))

        occupant_row = self.db.fetchone("""
            SELECT id FROM occupant
            WHERE account_id = ? AND room_jid_id = ? AND nick = ?
        """, (self.account_id, room_jid_id, our_nick))

        if not occupant_row:
            if self.logger:
                self.logger.error(f"Failed to get occupant.id for {our_nick}")
            return

        occupant_id = occupant_row['id']

        if emoji:
            # Store MUC reaction using occupant_id
            self.db.execute("""
                INSERT INTO reaction (account_id, content_item_id, occupant_id, time, emojis)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, content_item_id, occupant_id)
                DO UPDATE SET emojis = excluded.emojis, time = excluded.time
            """, (self.account_id, content_item_id, occupant_id, reaction_time, emoji))
        else:
            # Remove MUC reaction
            self.db.execute("""
                DELETE FROM reaction
                WHERE account_id = ? AND content_item_id = ? AND occupant_id = ?
            """, (self.account_id, content_item_id, occupant_id))

    def _store_sent_chat_reaction(self, content_item_id, emoji, reaction_time):
        """Store our own sent 1-1 chat reaction locally."""
        # Get our own jid_id
        our_jid = self.client.boundjid.bare
        jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (our_jid,))
        if not jid_row:
            # Create JID entry for ourselves
            self.db.execute("INSERT OR IGNORE INTO jid (bare_jid) VALUES (?)", (our_jid,))
            self.db.commit()
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (our_jid,))
            if not jid_row:
                if self.logger:
                    self.logger.error(f"Failed to get jid_id for {our_jid}")
                return

        jid_id = jid_row['id']

        if emoji:
            # Store 1-1 reaction using jid_id
            self.db.execute("""
                INSERT INTO reaction (account_id, content_item_id, jid_id, time, emojis)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id, content_item_id, jid_id)
                DO UPDATE SET emojis = excluded.emojis, time = excluded.time
            """, (self.account_id, content_item_id, jid_id, reaction_time, emoji))
        else:
            # Remove 1-1 reaction
            self.db.execute("""
                DELETE FROM reaction
                WHERE account_id = ? AND content_item_id = ? AND jid_id = ?
            """, (self.account_id, content_item_id, jid_id))
