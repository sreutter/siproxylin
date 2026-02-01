"""
PresenceBarrel - Handles roster and presence management.

Responsibilities:
- Roster updates and synchronization (RFC 6121)
- Presence tracking (show/status)
- Subscription management (requests, approvals, cancellations)
"""

import logging
import asyncio
from typing import Optional


class PresenceBarrel:
    """Manages roster and presence for an account."""

    def __init__(self, account_id: int, client, db, logger, signals: dict):
        """
        Initialize presence barrel.

        Args:
            account_id: Account ID
            client: DrunkXMPP client instance (must be set before use)
            db: Database singleton (direct access)
            logger: Account logger instance
            signals: Dict of Qt signal references for emitting events
        """
        self.account_id = account_id
        self.client = client  # Will be None initially, set by brewery after connection
        self.db = db
        self.logger = logger
        self.signals = signals

    def get_contact_presence(self, jid: str) -> str:
        """
        Get presence for a contact.

        Args:
            jid: Contact JID

        Returns:
            Presence show value: 'available', 'away', 'xa', 'dnd', 'chat', or 'unavailable'
        """
        if not self.client or not self.client.client_roster:
            return 'unavailable'

        try:
            roster = self.client.client_roster
            if jid not in roster:
                return 'unavailable'

            # Get presence from roster
            presence = roster.presence(jid)
            if not presence:
                return 'unavailable'

            # presence is a dict of {resource: {show, status, priority}}
            # Get the "best" resource (highest priority or first available)
            best_show = 'unavailable'
            for resource, info in presence.items():
                show = info.get('show', 'available')
                if show in ('chat', 'available', ''):
                    return 'available'  # Any available resource counts as available
                elif show in ('away', 'xa', 'dnd'):
                    best_show = show  # Track away/xa/dnd

            return best_show

        except Exception as e:
            if self.logger:
                self.logger.debug(f"Error getting presence for {jid}: {e}")
            return 'unavailable'

    async def request_subscription(self, jid: str):
        """Request presence subscription from a contact (RFC 6121 §3.1.1)."""
        if not self.client:
            raise RuntimeError("Not connected")

        if self.logger:
            self.logger.info(f"Requesting subscription from {jid}")

        await self.client.request_subscription(jid)

    async def approve_subscription(self, jid: str):
        """Approve presence subscription request (RFC 6121 §3.1.3)."""
        if not self.client:
            raise RuntimeError("Not connected")

        if self.logger:
            self.logger.info(f"Approving subscription for {jid}")

        await self.client.approve_subscription(jid)

    async def deny_subscription(self, jid: str):
        """Deny presence subscription request (RFC 6121 §3.1.4)."""
        if not self.client:
            raise RuntimeError("Not connected")

        if self.logger:
            self.logger.info(f"Denying subscription for {jid}")

        await self.client.deny_subscription(jid)

    async def cancel_subscription(self, jid: str):
        """Cancel our presence subscription (RFC 6121 §3.2)."""
        if not self.client:
            raise RuntimeError("Not connected")

        if self.logger:
            self.logger.info(f"Cancelling subscription to {jid}")

        await self.client.cancel_subscription(jid)

    async def revoke_subscription(self, jid: str):
        """Revoke contact's subscription to our presence (RFC 6121 §3.2)."""
        if not self.client:
            raise RuntimeError("Not connected")

        if self.logger:
            self.logger.info(f"Revoking subscription for {jid}")

        await self.client.revoke_subscription(jid)

    async def _on_roster_update(self, event, fetch_avatars_callback):
        """
        Handle roster updates from XMPP server.

        Args:
            event: Roster update event from slixmpp
            fetch_avatars_callback: Callback to trigger avatar fetching (callable)
        """
        if not self.client:
            return

        if self.logger:
            self.logger.info("Roster update received, syncing to database...")

        try:
            # Get roster from slixmpp
            roster = self.client.client_roster

            # Track JIDs from server roster (excluding self)
            server_jids = set()

            # Iterate through roster items
            for jid_str in roster:
                if jid_str == self.client.boundjid.bare:
                    # Skip self
                    continue

                # Add to server JIDs set
                server_jids.add(jid_str)

                # Get roster item info
                item = roster[jid_str]
                try:
                    name = item['name'] or ''
                except (KeyError, TypeError):
                    name = ''

                try:
                    subscription = item['subscription'] or 'none'
                except (KeyError, TypeError):
                    subscription = 'none'

                try:
                    ask = item['ask'] or None
                except (KeyError, TypeError):
                    ask = None

                # Convert text subscription to boolean flags
                we_see_their_presence = 1 if subscription in ('to', 'both') else 0
                they_see_our_presence = 1 if subscription in ('from', 'both') else 0
                we_requested_subscription = 1 if ask == 'subscribe' else 0

                # Get or create JID entry
                jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid_str,))
                if jid_row:
                    jid_id = jid_row['id']
                else:
                    cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (jid_str,))
                    jid_id = cursor.lastrowid

                # Insert/update roster entry with boolean fields
                self.db.execute("""
                    INSERT INTO roster (account_id, jid_id, name, subscription,
                                      we_see_their_presence, they_see_our_presence,
                                      we_requested_subscription)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (account_id, jid_id) DO UPDATE SET
                        name = excluded.name,
                        subscription = excluded.subscription,
                        we_see_their_presence = excluded.we_see_their_presence,
                        they_see_our_presence = excluded.they_see_our_presence,
                        we_requested_subscription = excluded.we_requested_subscription
                """, (self.account_id, jid_id, name, subscription,
                      we_see_their_presence, they_see_our_presence, we_requested_subscription))

            # Remove contacts from local DB that are no longer in server roster
            # This handles contacts deleted from other devices or via other clients
            # TODO: Proper event-driven architecture - hook roster properly into the
            #       protocol callbacks rather than optimistic GUI updates. Currently
            #       GUI deletes from DB immediately, then this sync runs. Should be:
            #       GUI sends XMPP IQ → server processes → roster push → callback updates DB → GUI updates
            local_contacts = self.db.fetchall("""
                SELECT r.id, j.bare_jid
                FROM roster r
                JOIN jid j ON r.jid_id = j.id
                WHERE r.account_id = ?
            """, (self.account_id,))

            for row in local_contacts:
                jid_str = row['bare_jid']
                roster_id = row['id']

                # If contact is in local DB but NOT in server roster, delete it
                if jid_str not in server_jids:
                    if self.logger:
                        self.logger.info(f"Removing contact {jid_str} - no longer in server roster")

                    # Delete from roster (messages/history remain untouched by this sync)
                    self.db.execute("DELETE FROM roster WHERE id = ?", (roster_id,))

            self.db.commit()

            if self.logger:
                self.logger.info(f"Roster synced: {len(roster)} contacts")

            # Emit signal to notify GUI
            self.signals['roster_updated'].emit(self.account_id)

            # Fetch avatars for roster contacts in background
            # (AvatarBarrel handles its own throttling - once per minute max)
            if fetch_avatars_callback:
                asyncio.create_task(fetch_avatars_callback())

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to sync roster: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    async def _on_presence_changed(self, from_jid: str, show: str):
        """
        Handle presence change notification (RFC 6121).
        Emits signal for GUI to update presence indicators in roster.

        Args:
            from_jid: Contact's bare JID
            show: Presence show value ('available', 'away', 'xa', 'dnd', 'unavailable')
        """
        if self.logger:
            self.logger.debug(f"Presence from {from_jid}: {show}")

        # Emit signal for GUI to update presence indicator
        self.signals['presence_changed'].emit(self.account_id, from_jid, show)

    async def _on_subscription_request(self, from_jid: str):
        """
        Handle incoming presence subscription request (RFC 6121 §3.1.2).
        Emits signal for GUI to show approval dialog.

        Args:
            from_jid: JID of person requesting subscription
        """
        if self.logger:
            self.logger.info(f"Subscription request from {from_jid}")

        # Emit signal for GUI to handle
        self.signals['subscription_request_received'].emit(self.account_id, from_jid)

    async def _on_subscription_changed(self, from_jid: str, change_type: str):
        """
        Handle subscription state change (RFC 6121).
        Roster is automatically updated by slixmpp, we need to sync to DB.

        Args:
            from_jid: JID whose subscription changed
            change_type: Type of change ('subscribed', 'unsubscribed', 'unsubscribe')
        """
        if self.logger:
            self.logger.info(f"Subscription changed for {from_jid}: {change_type}")

        # Get updated subscription state from slixmpp roster
        if self.client and self.client.client_roster:
            try:
                roster = self.client.client_roster
                if from_jid in roster:
                    item = roster[from_jid]

                    # Access RosterItem attributes with dict-style brackets (not .get())
                    try:
                        subscription = item['subscription'] or 'none'
                    except (KeyError, TypeError):
                        subscription = 'none'

                    try:
                        ask = item['ask'] or None
                    except (KeyError, TypeError):
                        ask = None

                    # Convert to boolean flags
                    we_see_their_presence = 1 if subscription in ('to', 'both') else 0
                    they_see_our_presence = 1 if subscription in ('from', 'both') else 0
                    we_requested_subscription = 1 if ask == 'subscribe' else 0

                    # Get or create JID entry
                    jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (from_jid,))
                    if jid_row:
                        jid_id = jid_row['id']
                    else:
                        cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (from_jid,))
                        jid_id = cursor.lastrowid

                    # Track if THEY have a pending subscription request to US
                    # This is tracked via change_type, not roster (roster doesn't store incoming requests)
                    # Get current value from DB first
                    roster_row = self.db.fetchone(
                        "SELECT they_requested_subscription FROM roster WHERE account_id = ? AND jid_id = ?",
                        (self.account_id, jid_id)
                    )
                    they_requested_subscription = roster_row['they_requested_subscription'] if roster_row else 0

                    # Update based on change_type
                    if change_type == 'subscribe':
                        # They just sent us a subscription request
                        they_requested_subscription = 1
                    elif change_type in ('subscribed', 'unsubscribed', 'unsubscribe'):
                        # Request was approved/denied/cancelled - clear the flag
                        they_requested_subscription = 0
                    # Otherwise preserve existing value

                    if self.logger:
                        self.logger.info(f"Syncing subscription state for {from_jid}: {subscription} (ask={ask}, change={change_type})")
                        self.logger.info(f"  Boolean flags: we_see={we_see_their_presence}, they_see={they_see_our_presence}, we_req={we_requested_subscription}, they_req={they_requested_subscription}")

                    # Update roster subscription in DB with boolean fields
                    self.db.execute("""
                        INSERT INTO roster (account_id, jid_id, name, subscription,
                                          we_see_their_presence, they_see_our_presence,
                                          we_requested_subscription, they_requested_subscription)
                        VALUES (?, ?, '', ?, ?, ?, ?, ?)
                        ON CONFLICT (account_id, jid_id) DO UPDATE SET
                            subscription = excluded.subscription,
                            we_see_their_presence = excluded.we_see_their_presence,
                            they_see_our_presence = excluded.they_see_our_presence,
                            we_requested_subscription = excluded.we_requested_subscription,
                            they_requested_subscription = excluded.they_requested_subscription
                    """, (self.account_id, jid_id, subscription,
                          we_see_their_presence, they_see_our_presence, we_requested_subscription, they_requested_subscription))
                    self.db.commit()

                    if self.logger:
                        self.logger.info(f"Database updated: {from_jid} subscription flags synced")

            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to sync subscription state: {e}")
                    import traceback
                    self.logger.error(traceback.format_exc())

        # Emit signal for GUI to update roster
        self.signals['subscription_changed'].emit(self.account_id, from_jid, change_type)

        # Trigger roster refresh
        self.signals['roster_updated'].emit(self.account_id)
