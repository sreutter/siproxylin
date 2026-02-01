"""
AvatarBarrel - Handles avatar fetching and storage.

Responsibilities:
- Avatar fetching (XEP-0153, XEP-0084)
- Avatar storage to database
- Avatar caching and throttling
"""

import logging
import time
from typing import Optional


class AvatarBarrel:
    """Manages avatars for an account."""

    def __init__(self, account_id: int, client, db, logger, signals: dict):
        """
        Initialize avatar barrel.

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

        # Throttle avatar fetches (once per minute max)
        self._last_avatar_fetch = 0

    async def on_avatar_update(self, jid: str, avatar_data: dict):
        """
        Handle avatar update from DrunkXMPP (XEP-0084/0153).
        Stores avatar in database and emits signal to GUI.

        Args:
            jid: Bare JID of entity
            avatar_data: Dict with keys: 'data' (bytes), 'hash' (str), 'mime_type' (str), 'source' (str)
        """
        if self.logger:
            source = avatar_data.get('source', 'unknown').upper()
            size = len(avatar_data.get('data', b''))
            self.logger.info(f"Avatar updated for {jid}: {size} bytes from {source}")

        try:
            # Store avatar in database
            self.store_avatar(jid, avatar_data)

            # Emit signal to refresh GUI
            self.signals['avatar_updated'].emit(self.account_id, jid)

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to handle avatar update for {jid}: {e}")
                import traceback
                self.logger.error(traceback.format_exc())

    def store_avatar(self, jid: str, avatar_data: dict):
        """
        Store avatar in database.

        Args:
            jid: Bare JID
            avatar_data: Dict with 'data', 'hash', 'mime_type', 'source'
        """
        # Get or create JID entry
        jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid,))
        if jid_row:
            jid_id = jid_row['id']
        else:
            cursor = self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (jid,))
            jid_id = cursor.lastrowid

        # Determine avatar type: 0=vCard, 1=PEP
        avatar_type = 1 if avatar_data.get('source') == 'xep_0084' else 0

        # Store avatar (REPLACE on conflict to update)
        self.db.execute("""
            INSERT INTO contact_avatar (jid_id, account_id, hash, type, data)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (jid_id, account_id, type) DO UPDATE SET
                hash = excluded.hash,
                data = excluded.data
        """, (
            jid_id,
            self.account_id,
            avatar_data['hash'],
            avatar_type,
            avatar_data['data']
        ))

        self.db.commit()

        if self.logger:
            self.logger.debug(f"Avatar stored for {jid} (type={avatar_type}, hash={avatar_data['hash'][:16]}...)")

    async def fetch_roster_avatars(self):
        """
        Fetch avatars for all roster contacts.
        Called after roster is loaded on connection.
        Throttled to once per minute to prevent spam.
        """
        if not self.client:
            return

        # Throttle: Only fetch once per minute
        now = time.time()
        if now - self._last_avatar_fetch < 60:
            if self.logger:
                self.logger.debug(f"Skipping avatar fetch (throttled, {int(60 - (now - self._last_avatar_fetch))}s remaining)")
            return

        self._last_avatar_fetch = now

        if self.logger:
            self.logger.info("Fetching avatars for roster contacts...")

        try:
            # Get all roster JIDs
            roster_entries = self.db.fetchall("""
                SELECT j.bare_jid
                FROM roster r
                JOIN jid j ON r.jid_id = j.id
                WHERE r.account_id = ?
            """, (self.account_id,))

            if self.logger:
                self.logger.info(f"Found {len(roster_entries)} roster contacts")

            # Fetch avatars asynchronously (don't block on each one)
            for entry in roster_entries:
                jid = entry['bare_jid']
                try:
                    # Check if we already have a recent avatar
                    cached = self.db.fetchone("""
                        SELECT hash FROM contact_avatar
                        WHERE jid_id = (SELECT id FROM jid WHERE bare_jid = ?)
                        AND account_id = ?
                        ORDER BY type DESC
                        LIMIT 1
                    """, (jid, self.account_id))

                    # Always fetch to ensure we have the latest
                    # (could optimize later with timestamp checks)
                    avatar_data = await self.client.get_avatar(jid)

                    if avatar_data:
                        if self.logger:
                            self.logger.debug(f"Fetched avatar for {jid}")
                    else:
                        if self.logger:
                            self.logger.debug(f"No avatar for {jid}")

                except Exception as e:
                    if self.logger:
                        self.logger.debug(f"Failed to fetch avatar for {jid}: {e}")

            if self.logger:
                self.logger.info("Roster avatar fetch completed")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to fetch roster avatars: {e}")
                import traceback
                self.logger.error(traceback.format_exc())
