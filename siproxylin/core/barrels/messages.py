"""
MessageBarrel - Handles message operations.

Responsibilities:
- Message sending/receiving (private and MUC)
- Message corrections (XEP-0308)
- Reactions (XEP-0444)
- Chat state notifications (XEP-0085)
- Message receipts (XEP-0184) and markers (XEP-0333)
- Server acknowledgements (XEP-0198)
"""

import logging
from typing import Optional


class MessageBarrel:
    """Manages messages for an account."""

    def __init__(self, account_id: int, client, db, logger, signals: dict, receipt_handler, files_barrel):
        """
        Initialize message barrel.

        Args:
            account_id: Account ID
            client: DrunkXMPP client instance (must be set before use)
            db: Database singleton (direct access)
            logger: Account logger instance
            signals: Dict of Qt signal references for emitting events
            receipt_handler: ReceiptHandler instance for receipt/marker updates
            files_barrel: FileBarrel instance for handling file attachments
        """
        self.account_id = account_id
        self.client = client  # Will be None initially, set by brewery after connection
        self.db = db
        self.logger = logger
        self.signals = signals
        self.receipt_handler = receipt_handler
        self.files_barrel = files_barrel

    async def send_message(self, to_jid: str, message: str, encrypted: bool = False):
        """
        Send a message.

        Args:
            to_jid: Recipient JID
            message: Message text
            encrypted: Use OMEMO encryption
        """
        if not self.client:
            raise RuntimeError("Not connected")

        if self.logger:
            enc_str = "encrypted" if encrypted else "plaintext"
            self.logger.info(f"Sending {enc_str} message to {to_jid}")

        if encrypted:
            return await self.client.send_encrypted_private_message(to_jid, message)
        else:
            return await self.client.send_private_message(to_jid, message)

    def _is_message_from_us(self, metadata, counterpart_jid: str) -> bool:
        """
        Check if a message is from our account (any device).

        Args:
            metadata: MessageMetadata from DrunkXMPP
            counterpart_jid: The JID of the conversation (room for MUC, peer for 1-1)

        Returns:
            True if message is from our account (this or another device), False otherwise
        """
        # 1-1 Chat Messages
        if metadata.message_type == 'chat':
            # Carbon sent messages are from us
            if metadata.is_carbon and metadata.carbon_type == 'sent':
                return True

            # Direct message - check if from our own JID
            from_bare_jid = counterpart_jid.split('/')[0] if '/' in counterpart_jid else counterpart_jid
            our_bare_jid = self.client.boundjid.bare if self.client else None

            return our_bare_jid and from_bare_jid == our_bare_jid

        # MUC Messages
        elif metadata.message_type == 'groupchat':
            room_jid = counterpart_jid
            our_occupant_id = self.client.own_occupant_ids.get(room_jid) if self.client else None

            # Primary: Check occupant-id (XEP-0421)
            if metadata.occupant_id and our_occupant_id and metadata.occupant_id == our_occupant_id:
                return True

            # Fallback: Check nickname (for servers without XEP-0421 support)
            if metadata.muc_nick and self.client and room_jid in self.client.rooms:
                our_nick = self.client.rooms[room_jid].get('nick')
                if our_nick and metadata.muc_nick.lower() == our_nick.lower():
                    return True

            return False

        return False

    def _classify_message(self, metadata, counterpart_jid: str) -> dict:
        """
        Classify a message based on metadata from DrunkXMPP.

        Clean 3-step classification logic:
        1. Check if duplicate (for ALL messages - peer and ours)
        2. Check if from us (this device or another device)
        3. Return classification with action, direction, and carbon flag

        Args:
            metadata: MessageMetadata from DrunkXMPP
            counterpart_jid: The JID of the conversation (room for MUC, peer for 1-1)

        Returns:
            {
                'action': 'store' | 'update' | 'skip',
                'direction': 0 | 1,  # 0=received, 1=sent
                'is_duplicate': bool,
                'is_from_other_device': bool
            }
        """
        # Skip empty messages (no body and no attachment)
        if not metadata.has_body and not metadata.has_attachment:
            return {
                'action': 'skip',
                'direction': 0,
                'is_duplicate': False,
                'is_from_other_device': False
            }

        # Step 1: Check for duplicate (for ALL messages - peer AND ours)
        # This prevents duplicates on MUC rejoin, MAM history, etc.
        is_duplicate = self._check_message_duplicate(
            metadata.message_id,
            metadata.origin_id,
            metadata.stanza_id
        )

        if is_duplicate:
            # Message already in database
            # For messages from us (reflection), update marked status
            # For peer messages (MAM history), skip entirely
            is_from_us = self._is_message_from_us(metadata, counterpart_jid)

            if is_from_us:
                # Reflection from THIS device - update marked status (server ACK)
                return {
                    'action': 'update',
                    'direction': 1,
                    'is_duplicate': True,
                    'is_from_other_device': False
                }
            else:
                # Peer message we've already stored (e.g., from MAM history)
                return {
                    'action': 'skip',
                    'direction': 0,
                    'is_duplicate': True,
                    'is_from_other_device': False
                }

        # Step 2: Not a duplicate - check if from us
        is_from_us = self._is_message_from_us(metadata, counterpart_jid)

        # Step 3: Return classification
        if is_from_us:
            # Message from our account (another device)
            # Store as sent with carbon flag
            return {
                'action': 'store',
                'direction': 1,  # sent
                'is_duplicate': False,
                'is_from_other_device': True
            }
        else:
            # Message from peer
            # Store as received
            return {
                'action': 'store',
                'direction': 0,  # received
                'is_duplicate': False,
                'is_from_other_device': False
            }

    def _check_message_duplicate(self, message_id: Optional[str], origin_id: Optional[str],
                                  stanza_id: Optional[str]) -> bool:
        """
        Check if a message or file already exists in the database.

        Used for deduplication when receiving messages/files (live or from MAM history).
        Checks both message and file_transfer tables.
        Checks in priority order per XEP-0359:
        1. stanza_id (most reliable - server-assigned, unspoofable)
        2. origin_id (client-assigned, stable across hops)
        3. message_id (basic message id, least reliable)

        Args:
            message_id: Message ID from 'id' attribute (least reliable)
            origin_id: Origin ID - client-assigned (XEP-0359)
            stanza_id: Server-assigned stanza-id (XEP-0359) - most reliable

        Returns:
            True if message/file exists in DB, False otherwise
        """
        if not message_id and not origin_id and not stanza_id:
            return False

        # Priority 1: stanza_id (most reliable - server-assigned, unspoofable per XEP-0359)
        if stanza_id:
            # Check message table
            result = self.db.fetchone("""
                SELECT id FROM message
                WHERE account_id = ? AND stanza_id = ?
                LIMIT 1
            """, (self.account_id, stanza_id))
            if result:
                return True

            # Check file_transfer table
            result = self.db.fetchone("""
                SELECT id FROM file_transfer
                WHERE account_id = ? AND stanza_id = ?
                LIMIT 1
            """, (self.account_id, stanza_id))
            if result:
                return True

        # Priority 2: origin_id (client-assigned, stable across hops)
        if origin_id:
            # Check message table
            result = self.db.fetchone("""
                SELECT id FROM message
                WHERE account_id = ? AND origin_id = ?
                LIMIT 1
            """, (self.account_id, origin_id))
            if result:
                return True

            # Check file_transfer table
            result = self.db.fetchone("""
                SELECT id FROM file_transfer
                WHERE account_id = ? AND origin_id = ?
                LIMIT 1
            """, (self.account_id, origin_id))
            if result:
                return True

        # Priority 3: message_id (basic message id, least reliable)
        if message_id:
            # Check message table
            result = self.db.fetchone("""
                SELECT id FROM message
                WHERE account_id = ? AND message_id = ?
                LIMIT 1
            """, (self.account_id, message_id))
            if result:
                return True

            # Check file_transfer table
            result = self.db.fetchone("""
                SELECT id FROM file_transfer
                WHERE account_id = ? AND message_id = ?
                LIMIT 1
            """, (self.account_id, message_id))
            if result:
                return True

        return False

    def _update_message_marked(self, message_id: Optional[str], origin_id: Optional[str],
                               stanza_id: Optional[str], marked: int):
        """
        Update the marked status of a message (for reflections from this device).
        Also updates stanza_id if provided (MUC reflections provide server-assigned stanza-id).

        Args:
            message_id: Message ID from 'id' attribute
            origin_id: Origin ID (XEP-0359)
            stanza_id: Server-assigned stanza-id (XEP-0359)
            marked: New marked value (1=sent, 2=delivered, 7=displayed)
        """
        if not message_id and not origin_id and not stanza_id:
            return

        try:
            # Update marked and stanza_id (if provided)
            # For MUC: reflection includes stanza-id from server, we need to store it for reactions
            if stanza_id:
                # Update message table (has both marked and stanza_id)
                result = self.db.execute("""
                    UPDATE message
                    SET marked = ?, stanza_id = ?
                    WHERE account_id = ?
                      AND (message_id = ? OR origin_id = ? OR stanza_id = ?)
                """, (marked, stanza_id, self.account_id, message_id, origin_id, stanza_id))

                # Update file_transfer table (only stanza_id - file_transfer uses 'state' not 'marked')
                file_result = self.db.execute("""
                    UPDATE file_transfer
                    SET stanza_id = ?
                    WHERE account_id = ?
                      AND (message_id = ? OR origin_id = ? OR stanza_id = ?)
                """, (stanza_id, self.account_id, message_id, origin_id, stanza_id))

                total_updated = result.rowcount + file_result.rowcount
            else:
                # Update message table only (no stanza_id to update)
                result = self.db.execute("""
                    UPDATE message
                    SET marked = ?
                    WHERE account_id = ?
                      AND (message_id = ? OR origin_id = ? OR stanza_id = ?)
                """, (marked, self.account_id, message_id, origin_id, stanza_id))

                total_updated = result.rowcount

            if total_updated > 0:
                self.db.commit()
                if self.logger:
                    self.logger.debug(f"Updated {total_updated} message(s)/file(s) marked={marked}, stanza_id={stanza_id if stanza_id else 'N/A'}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to update message marked status: {e}")

    async def _on_message(self, room, nick, body, metadata, msg):
        """
        Handle incoming MUC message (both live and history).

        Args:
            room: Room JID
            nick: Sender nickname
            body: Message body
            metadata: MessageMetadata from DrunkXMPP
            msg: Full stanza
        """
        # Classify the message
        classification = self._classify_message(metadata, room)

        if self.logger:
            enc_str = f"[{metadata.encryption_type.upper()}]" if metadata.is_encrypted else "[PLAINTEXT]"
            history_str = "[HISTORY]" if metadata.is_history else "[LIVE]"
            action_str = classification['action'].upper()
            dir_str = "SENT" if classification['direction'] == 1 else "RECV"
            self.logger.info(f"MUC {history_str} {enc_str} {dir_str} {action_str} from {room}/{nick}: {body[:50] if body else '(attachment)'}...")

        # Handle based on classification
        if classification['action'] == 'skip':
            if self.logger:
                self.logger.debug(f"Skipping MUC message (empty or filtered)")
            return

        if classification['action'] == 'update':
            # Reflection from THIS device - update marked status
            if self.logger:
                self.logger.debug(f"Updating MUC message reflection (message_id: {metadata.message_id})")
            self._update_message_marked(metadata.message_id, metadata.origin_id, metadata.stanza_id, marked=1)
            return

        # Store MUC message in database (action == 'store')
        try:
            from datetime import datetime

            # Get timestamp from metadata
            if metadata.is_history and metadata.delay_timestamp:
                timestamp = int(metadata.delay_timestamp.timestamp())
            else:
                timestamp = int(datetime.now().timestamp())

            # Get or create JID entry for room
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (room,))
            if jid_row:
                jid_id = jid_row['id']
            else:
                cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (room,))
                jid_id = cursor.lastrowid

            # Get message IDs from metadata
            message_id = metadata.message_id
            origin_id = metadata.origin_id
            stanza_id = metadata.stanza_id

            # Additional duplicate check (safety - classifier should have caught this)
            if classification['is_duplicate']:
                if self.logger:
                    self.logger.debug(f"MUC message is duplicate, should have been handled already")
                return

            # Get conversation
            conversation_id = self.db.get_or_create_conversation(self.account_id, jid_id, 1)  # type=1 MUC

            # Get direction from classification
            direction = classification['direction']
            is_from_other_device = classification['is_from_other_device']

            # Handle file attachment OR regular message (mutually exclusive, as separate content items)
            if metadata.has_attachment:
                # File attachment - don't create message record, only file_transfer
                # Skip ONLY if this is a duplicate (reflection from THIS device)
                # For files from OTHER devices, we need to download and show them
                if classification['is_duplicate']:
                    if self.logger:
                        self.logger.debug(f"Skipping file_transfer - duplicate from THIS device")
                else:
                    # Download and create file_transfer for:
                    # - Files from peers (direction=0)
                    # - Files from our OTHER devices (direction=1, is_from_other_device=True)
                    await self.files_barrel.handle_incoming_file(
                        jid_id=jid_id,
                        from_jid=room,  # Use room JID as sender for MUC files
                        file_url=metadata.attachment_url,
                        is_encrypted=metadata.is_encrypted,
                        timestamp=timestamp,
                        conversation_id=conversation_id,
                        direction=direction,  # Pass direction to handler
                        is_from_other_device=is_from_other_device,  # Mark if from other device
                        message_id=message_id,  # For deduplication
                        origin_id=origin_id,  # For deduplication
                        stanza_id=stanza_id   # For deduplication
                    )
            else:
                # Regular text message (not a file)
                # Insert MUC message with type=1 (groupchat) and nickname in counterpart_resource
                result = self.db.insert_message_atomic(
                    account_id=self.account_id,
                    counterpart_id=jid_id,
                    conversation_id=conversation_id,
                    direction=direction,  # 0=received from peer, 1=sent from this/other device
                    msg_type=1,  # type=1 (groupchat/MUC)
                    time=timestamp,
                    local_time=timestamp,
                    body=body,
                    encryption=1 if metadata.is_encrypted else 0,
                    marked=1 if is_from_other_device else 0,  # FIX: Carbons already sent
                    is_carbon=1 if is_from_other_device else 0,
                    message_id=message_id,
                    origin_id=origin_id,
                    stanza_id=stanza_id,
                    counterpart_resource=nick,  # MUC nickname
                    reply_to_id=metadata.reply_to_id,
                    reply_to_jid=metadata.reply_to_jid
                )

                if result == (None, None):
                    if self.logger:
                        self.logger.debug("MUC message was duplicate, skipped by atomic insert")
                    return

                db_message_id, _ = result
                if self.logger and metadata.reply_to_id:
                    self.logger.debug(f"Stored reply metadata for message {db_message_id} -> {metadata.reply_to_id}")

            self.db.commit()

            if self.logger:
                self.logger.debug(f"MUC message stored in database (direction={direction})")

            # Emit signal to notify GUI only for live INCOMING messages (not history, not our sent messages)
            # History messages should not trigger notifications or unread counts
            # Our sent messages (direction=1, carbons) should not trigger notifications
            if not metadata.is_history and direction == 0:
                self.signals['message_received'].emit(self.account_id, room, False)

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to store MUC message: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    async def _on_private_message(self, from_jid, body, metadata, msg):
        """
        Handle incoming private message AND carbon copies (XEP-0280).

        Args:
            from_jid: Sender JID
            body: Message body
            metadata: MessageMetadata from DrunkXMPP
            msg: Full stanza
        """
        # Classify the message (handles both regular messages and carbon copies)
        classification = self._classify_message(metadata, from_jid)

        # Log with carbon/encryption info
        if self.logger:
            carbon_str = f"[CARBON {metadata.carbon_type.upper()}]" if metadata.is_carbon else ""
            enc_str = f"[{metadata.encryption_type.upper()}]" if metadata.is_encrypted else "[PLAINTEXT]"
            history_str = "[HISTORY]" if metadata.is_history else "[LIVE]"
            dir_str = "SENT" if classification['direction'] == 1 else "RECV"
            action_str = classification['action'].upper()
            self.logger.info(f"1-1 {history_str} {carbon_str} {enc_str} {dir_str} {action_str} {from_jid}: {body[:50] if body else '(attachment)'}...")

        # Handle based on classification
        if classification['action'] == 'skip':
            if self.logger:
                self.logger.debug(f"Skipping 1-1 message (empty or filtered)")
            return

        # Store message in database (action == 'store')
        try:
            from datetime import datetime

            # Get timestamp from metadata (respects delay for history)
            if metadata.is_history and metadata.delay_timestamp:
                timestamp = int(metadata.delay_timestamp.timestamp())
            else:
                timestamp = int(datetime.now().timestamp())

            # Get or create JID entry
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (from_jid,))
            if jid_row:
                jid_id = jid_row['id']
            else:
                cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (from_jid,))
                jid_id = cursor.lastrowid

            # Get message IDs from metadata
            message_id = metadata.message_id
            origin_id = metadata.origin_id
            stanza_id = metadata.stanza_id

            # Get direction and carbon flag from classification
            direction = classification['direction']
            is_from_other_device = classification['is_from_other_device']

            # Get conversation
            conversation_id = self.db.get_or_create_conversation(self.account_id, jid_id, 0)  # type=0 chat

            # Handle file attachment OR regular message (mutually exclusive, as separate content items)
            if metadata.has_attachment:
                # File attachment - don't create message record, only file_transfer
                await self.files_barrel.handle_incoming_file(
                    jid_id=jid_id,
                    from_jid=from_jid,
                    file_url=metadata.attachment_url,
                    is_encrypted=metadata.is_encrypted,
                    timestamp=timestamp,
                    conversation_id=conversation_id,
                    direction=direction,  # Pass direction from classification (0=received, 1=sent from other device)
                    is_from_other_device=is_from_other_device,  # Mark if from other device (carbon)
                    message_id=message_id,  # For deduplication
                    origin_id=origin_id,  # For deduplication
                    stanza_id=stanza_id   # For deduplication
                )
            else:
                # Regular text message (not a file)
                result = self.db.insert_message_atomic(
                    account_id=self.account_id,
                    counterpart_id=jid_id,
                    conversation_id=conversation_id,
                    direction=direction,  # 0=received, 1=sent (from other device)
                    msg_type=0,  # type=0 (chat)
                    time=timestamp,
                    local_time=timestamp,
                    body=body,
                    encryption=1 if metadata.is_encrypted else 0,
                    marked=1 if is_from_other_device else 0,  # FIX: Carbons already sent
                    is_carbon=1 if is_from_other_device else 0,
                    message_id=message_id,
                    origin_id=origin_id,
                    stanza_id=stanza_id,
                    reply_to_id=metadata.reply_to_id,
                    reply_to_jid=metadata.reply_to_jid
                )

                if result == (None, None):
                    if self.logger:
                        self.logger.debug("Private message was duplicate, skipped by atomic insert")
                    return

                db_message_id, _ = result
                if self.logger and metadata.reply_to_id:
                    self.logger.debug(f"Stored reply metadata for message {db_message_id} -> {metadata.reply_to_id}")

            self.db.commit()

            if self.logger:
                self.logger.debug(f"Private message stored in database (direction={direction}, is_carbon={1 if is_from_other_device else 0})")

            # Emit signal to notify GUI only for live INCOMING messages (not history, not our sent messages)
            # Our sent messages (direction=1, carbons) should not trigger notifications
            if not metadata.is_history and direction == 0:
                self.signals['message_received'].emit(self.account_id, from_jid, False)

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to store private message: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    async def _on_message_correction(self, from_jid, corrected_id, new_body, is_encrypted, msg):
        """
        Handle incoming message corrections (XEP-0308).

        Args:
            from_jid: JID of the sender
            corrected_id: ID of the message being corrected
            new_body: New message text
            is_encrypted: Whether the correction is encrypted
            msg: Full XMPP message stanza
        """
        if not self.db:
            return

        if self.logger:
            self.logger.info(f"Message correction from {from_jid}: msg {corrected_id} -> \"{new_body[:50]}...\"")

        try:
            # Update message in database by finding it via message_id, origin_id, or stanza_id
            result = self.db.execute("""
                UPDATE message
                SET body = ?
                WHERE (message_id = ? OR origin_id = ? OR stanza_id = ?)
                AND account_id = ?
            """, (new_body, corrected_id, corrected_id, corrected_id, self.account_id))

            if result.rowcount > 0:
                self.db.commit()
                if self.logger:
                    self.logger.debug(f"Updated {result.rowcount} message(s) in database")

                # Emit signal to refresh GUI (use is_marker=True to indicate it's a state change, not new message)
                self.signals['message_received'].emit(self.account_id, from_jid, True)
            else:
                if self.logger:
                    self.logger.warning(f"Message {corrected_id} not found in database for correction")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to update corrected message: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    async def _on_message_error(self, from_jid, to_jid, error_type, error_condition, error_text, origin_id):
        """
        Handle message errors.

        Updates the message status to error (marked=8) and stores the error text.

        Args:
            from_jid: JID that returned the error
            to_jid: Original recipient JID
            error_type: Error type ('cancel', 'modify', etc.)
            error_condition: Error condition ('item-not-found', 'forbidden', etc.)
            error_text: User-friendly error message
            origin_id: Origin ID of the failed message (XEP-0359)
        """
        try:
            if not origin_id:
                if self.logger:
                    self.logger.warning(f"Message error from {from_jid} but no origin-id to match: {error_text}")
                return

            # Find message in database by origin_id
            # Update status to error (marked=8) and store error_text
            result = self.db.execute("""
                UPDATE message
                SET marked = 8, error_text = ?
                WHERE account_id = ? AND origin_id = ?
            """, (error_text, self.account_id, origin_id))

            self.db.commit()

            if result.rowcount > 0:
                if self.logger:
                    self.logger.info(f"Marked message {origin_id} as error: {error_text}")

                # Emit signal to refresh GUI
                self.signals['message_received'].emit(self.account_id, from_jid, True)
            else:
                if self.logger:
                    self.logger.warning(f"Message {origin_id} not found for error update")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to handle message error: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def _on_receipt_received(self, from_jid: str, message_id: str):
        """
        Handle delivery receipt (XEP-0184).
        Calls receipt_handler to update database.

        Args:
            from_jid: Sender's bare JID
            message_id: Message origin_id (our sent message ID)
        """
        if self.logger:
            self.logger.info(f"Delivery receipt from {from_jid} for message {message_id}")

        try:
            self.receipt_handler.on_delivery_receipt(self.account_id, from_jid, message_id)
            # Emit signal to refresh UI immediately (receipt update, not new message)
            self.signals['message_received'].emit(self.account_id, from_jid, True)
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to process delivery receipt: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def _on_marker_received(self, from_jid: str, message_id: str, marker_type: str):
        """
        Handle chat marker (XEP-0333).
        Calls receipt_handler to update database based on marker type.

        Args:
            from_jid: Sender's bare JID
            message_id: Message origin_id
            marker_type: Type of marker ('received', 'displayed', 'acknowledged')
        """
        if self.logger:
            self.logger.info(f"Chat marker '{marker_type}' from {from_jid} for message {message_id}")

        try:
            if marker_type == 'displayed':
                # Displayed marker - mark as READ (cumulative)
                self.receipt_handler.on_displayed_marker(self.account_id, from_jid, message_id)
                # Emit signal to refresh UI immediately (marker update, not new message)
                self.signals['message_received'].emit(self.account_id, from_jid, True)
            elif marker_type == 'received':
                # Received marker - redundant with delivery receipt, ignore
                self.receipt_handler.on_received_marker(self.account_id, from_jid, message_id)
            elif marker_type == 'acknowledged':
                # Acknowledged marker - not currently handled
                if self.logger:
                    self.logger.debug(f"Acknowledged marker received but not handled")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to process chat marker: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def _on_reaction(self, metadata, message_id: str, emojis: list):
        """
        Handle incoming reaction (XEP-0444).
        Stores reaction in database in the database.

        For MUC: Uses occupant_id table to track nickname → occupant_id mapping
        For 1-1: Uses jid_id as before

        Args:
            metadata: MessageMetadata with reaction sender info
            message_id: ID of message being reacted to (origin_id/stanza_id/message_id)
            emojis: List of emoji strings (empty if reactions removed)
        """
        from slixmpp.jid import JID

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
            import time

            # Find the content_item by message_id
            # Try origin_id first, then stanza_id, then message_id
            # Search both message table (content_type=0) and file_transfer table (content_type=2)
            content_item = self.db.fetchone("""
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
                # Get or create occupant entry
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

            else:  # 1-1 chat
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

            self.db.commit()

            # Emit signal to refresh UI
            conversation_jid = JID(metadata.from_jid).bare if conv_type == 0 else JID(metadata.from_jid).bare
            self.signals['message_received'].emit(self.account_id, conversation_jid, True)

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to process reaction: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def _on_chat_state(self, from_jid: str, state: str):
        """
        Handle chat state notification (XEP-0085).
        Emits signal for GUI to display typing indicators.

        Args:
            from_jid: Sender's bare JID
            state: Chat state ('active', 'composing', 'paused', 'inactive', 'gone')
        """
        if self.logger:
            self.logger.debug(f"Chat state from {from_jid}: {state}")

        # Emit signal for GUI to update typing indicator
        self.signals['chat_state_changed'].emit(self.account_id, from_jid, state)

    def _on_server_ack(self, ack_info):
        """
        Handle server ACK (XEP-0198).
        Calls receipt_handler to update database.

        Args:
            ack_info: Object with msg_id attribute
        """
        message_id = ack_info.msg_id

        if self.logger:
            self.logger.info(f"Server ACK for message {message_id}")

        try:
            self.receipt_handler.on_server_ack(self.account_id, message_id)

            # Get counterpart JID to emit signal for UI refresh
            msg_row = self.db.fetchone(
                """
                SELECT j.bare_jid
                FROM message m
                JOIN jid j ON m.counterpart_id = j.id
                WHERE m.account_id = ? AND m.origin_id = ?
                """,
                (self.account_id, message_id)
            )

            if msg_row:
                self.signals['message_received'].emit(self.account_id, msg_row['bare_jid'], True)  # Server ACK, not new message
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to process server ACK: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    async def catchup_private_chats(self, max_messages_per_chat: int = 500):
        """
        Catch up on missed private chat messages via MAM (XEP-0313).
        Called on session start to retrieve messages sent while offline.

        Similar to MUC room catchup, but for 1-to-1 chats.
        MAM returns raw archived messages, not live messages, so we INSERT directly.

        Args:
            max_messages_per_chat: Maximum messages to retrieve per contact (default: 500)
        """
        if not self.client:
            return

        if self.logger:
            self.logger.info("Catching up on private chat messages via MAM...")

        try:
            # Get all conversations with existing messages (active chats)
            # Exclude MUC rooms (they have their own catchup)
            conversations = self.db.fetchall("""
                SELECT DISTINCT j.bare_jid, j.id as jid_id,
                       MAX(m.time) as latest_time
                FROM message m
                JOIN jid j ON m.counterpart_id = j.id
                WHERE m.account_id = ?
                  AND j.bare_jid NOT IN (
                      SELECT j2.bare_jid FROM bookmark b
                      JOIN jid j2 ON b.jid_id = j2.id
                      WHERE b.account_id = ?
                  )
                GROUP BY j.bare_jid, j.id
            """, (self.account_id, self.account_id))

            if not conversations:
                if self.logger:
                    self.logger.debug("No active private chats found for MAM catchup")
                return

            if self.logger:
                self.logger.info(f"Found {len(conversations)} active private chats for MAM catchup")

            for conv in conversations:
                contact_jid = conv['bare_jid']
                jid_id = conv['jid_id']
                latest_time = conv['latest_time']

                try:
                    await self._retrieve_private_chat_history(contact_jid, jid_id, latest_time, max_messages_per_chat)
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to catch up messages for {contact_jid}: {e}")

            if self.logger:
                self.logger.info("Private chat MAM catchup completed")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to catch up private chats: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    async def _retrieve_private_chat_history(self, contact_jid: str, jid_id: int, latest_time: int, max_messages: int):
        """
        Retrieve MAM history for a specific private chat and store in database.
        Follows same pattern as MUC._retrieve_muc_history().

        Args:
            contact_jid: Contact's bare JID
            jid_id: JID ID from database
            latest_time: Unix timestamp of latest message in DB
            max_messages: Maximum number of messages to retrieve
        """
        from datetime import datetime, timezone

        # Start from 1 hour before latest message for safe overlap (same as MUC)
        start_time = datetime.fromtimestamp(latest_time - 3600, tz=timezone.utc)

        if self.logger:
            self.logger.debug(f"Querying MAM for {contact_jid} since {start_time} (1h overlap)")

        # Retrieve history from MAM
        history = await self.client.retrieve_history(
            jid=contact_jid,
            start=start_time,
            max_messages=max_messages,
            with_jid=contact_jid  # Filter to this specific contact
        )

        if not history:
            if self.logger:
                self.logger.debug(f"No new MAM messages for {contact_jid}")
            return

        if self.logger:
            self.logger.info(f"Retrieved {len(history)} MAM messages for {contact_jid}")

        # Batch duplicate detection - check BOTH message and file_transfer tables
        # (prevents duplicates when OMEMO encrypted files fail to decrypt on re-retrieval)
        archive_ids = [msg_data.get('archive_id') for msg_data in history if msg_data.get('archive_id')]
        existing_stanza_ids = set()
        if archive_ids:
            placeholders = ','.join('?' * len(archive_ids))

            # Check message table
            existing_msgs = self.db.fetchall(f"""
                SELECT stanza_id FROM message
                WHERE account_id = ? AND counterpart_id = ? AND stanza_id IN ({placeholders})
            """, (self.account_id, jid_id, *archive_ids))

            # Check file_transfer table
            existing_files = self.db.fetchall(f"""
                SELECT stanza_id FROM file_transfer
                WHERE account_id = ? AND counterpart_id = ? AND stanza_id IN ({placeholders})
            """, (self.account_id, jid_id, *archive_ids))

            # Combine both sets
            existing_stanza_ids = {row['stanza_id'] for row in existing_msgs} | {row['stanza_id'] for row in existing_files}

        # Get our JID for direction detection
        our_jid = self.client.boundjid.bare if self.client else None

        # Store messages
        inserted_count = 0
        for msg_data in history:
            sender_jid = msg_data.get('jid')  # Bare JID of sender
            body = msg_data.get('body', '')
            timestamp = msg_data.get('timestamp')
            unix_time = int(timestamp.timestamp()) if timestamp else int(datetime.now(tz=timezone.utc).timestamp())
            is_encrypted = msg_data.get('is_encrypted', False)
            archive_id = msg_data.get('archive_id')
            archived_msg = msg_data.get('message')  # Raw stanza from MAM

            # Extract XEP-0359 IDs from archived message for reactions
            origin_id = None
            stanza_id = None
            if archived_msg:
                try:
                    origin_id = archived_msg['origin_id']['id'] if archived_msg['origin_id']['id'] else None
                except (KeyError, TypeError):
                    pass
                stanza_id = archived_msg.get('id')

            # Skip duplicates
            if archive_id and archive_id in existing_stanza_ids:
                if self.logger:
                    self.logger.debug(f"MAM message already exists (archive_id={archive_id}), skipping duplicate")
                continue

            # Determine direction and carbon flag
            # Messages from our JID in MAM are carbons (sent from another device)
            direction = 1 if sender_jid == our_jid else 0
            is_carbon = (sender_jid == our_jid)  # Carbon if from our own JID

            # Check for file attachment (XEP-0066: Out of Band Data)
            has_attachment = False
            attachment_url = None
            if archived_msg:
                try:
                    # Use slixmpp's OOB plugin to extract URL
                    oob_url = archived_msg['oob']['url']
                    if oob_url:
                        has_attachment = True
                        attachment_url = oob_url
                except (KeyError, TypeError):
                    # No OOB extension or empty URL
                    pass

            # Fallback: Check if body is an attachment URL (aesgcm:// or https://)
            # Some servers/clients put URL in body without OOB extension in MAM archives
            if not has_attachment and body:
                if body.startswith('aesgcm://') or (body.startswith('https://') and len(body.split()) == 1):
                    has_attachment = True
                    attachment_url = body

            # Get conversation
            conversation_id = self.db.get_or_create_conversation(self.account_id, jid_id, 0)  # type=0 for 1-1 chat

            # Handle file attachment OR regular message (mutually exclusive, like live messages)
            if has_attachment:
                # File attachment from MAM - create file_transfer record
                await self.files_barrel.handle_incoming_file(
                    jid_id=jid_id,
                    from_jid=contact_jid,
                    file_url=attachment_url,
                    is_encrypted=is_encrypted,
                    timestamp=unix_time,
                    conversation_id=conversation_id,
                    direction=direction,
                    is_from_other_device=is_carbon,
                    message_id=stanza_id,  # Sender's message ID (for reactions)
                    origin_id=origin_id,  # Sender's origin-id (XEP-0359)
                    stanza_id=archive_id  # MAM archive ID (for dedup)
                )
                inserted_count += 1
            else:
                # Regular text message (not a file)
                result = self.db.insert_message_atomic(
                    account_id=self.account_id,
                    counterpart_id=jid_id,
                    conversation_id=conversation_id,
                    direction=direction,
                    msg_type=0,  # type=0 (private chat)
                    time=unix_time,
                    local_time=unix_time,
                    body=body,
                    encryption=1 if is_encrypted else 0,
                    marked=1,  # marked=1 (already delivered, from archive)
                    is_carbon=1 if is_carbon else 0,
                    message_id=stanza_id,  # Sender's message ID (for reactions)
                    origin_id=origin_id,  # Sender's origin-id (XEP-0359, for reactions)
                    stanza_id=archive_id  # MAM archive result ID (for dedup)
                )

                if result != (None, None):
                    inserted_count += 1

        self.db.commit()

        if inserted_count > 0:
            if self.logger:
                self.logger.info(f"Stored {inserted_count} new MAM messages for {contact_jid}")

            # Emit signal to refresh chat view if open
            self.signals['message_received'].emit(self.account_id, contact_jid, False)
