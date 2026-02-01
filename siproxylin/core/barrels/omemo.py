"""
OmemoBarrel - Handles OMEMO device management.

Responsibilities:
- OMEMO device list management
- Device trust management
- Device fetching/announcing
"""

import logging
import time
from typing import Optional


class OmemoBarrel:
    """Manages OMEMO devices for an account."""

    def __init__(self, account_id: int, client, db, logger, signals: dict):
        """
        Initialize OMEMO barrel.

        Args:
            account_id: Account ID
            client: DrunkXMPP client instance (must be set before use)
            db: Database singleton (direct access)
            logger: Account logger instance
            signals: Dict of Qt signal references (not currently used)
        """
        self.account_id = account_id
        self.client = client  # Will be None initially, set by brewery after connection
        self.db = db
        self.logger = logger
        self.signals = signals

    async def sync_omemo_devices_to_db(self, jid: str):
        """
        Sync OMEMO devices from library to database for a specific JID.

        Args:
            jid: Bare JID to sync devices for
        """
        if not self.client:
            return

        try:
            # Get devices from drunk-xmpp library
            devices = await self.client.get_omemo_devices(jid)

            if not devices:
                if self.logger:
                    self.logger.debug(f"No OMEMO devices found for {jid}")
                return

            # Get or create JID in database
            jid_row = self.db.fetchone("SELECT id FROM jid WHERE bare_jid = ?", (jid,))
            if not jid_row:
                self.db.execute("INSERT INTO jid (bare_jid) VALUES (?)", (jid,))
                jid_id = self.db.lastrowid()
            else:
                jid_id = jid_row['id']

            # Map trust level names to integers
            trust_map = {
                'TRUSTED': 2,
                'BLINDLY_TRUSTED': 1,
                'UNDECIDED': 0,
                'DISTRUSTED': 3
            }

            # Sync devices to database
            for device in devices:
                device_id = device['device_id']
                identity_key = device['identity_key']
                trust_level = trust_map.get(device['trust_level'], 0)
                label = device.get('label')

                # Check if device exists
                existing = self.db.fetchone("""
                    SELECT id, last_seen FROM omemo_device
                    WHERE account_id = ? AND jid_id = ? AND device_id = ?
                """, (self.account_id, jid_id, device_id))

                now = int(time.time())

                if existing:
                    # Update existing device
                    self.db.execute("""
                        UPDATE omemo_device
                        SET identity_key = ?, trust_level = ?, last_seen = ?, label = ?
                        WHERE account_id = ? AND jid_id = ? AND device_id = ?
                    """, (identity_key, trust_level, now, label, self.account_id, jid_id, device_id))
                else:
                    # Insert new device
                    self.db.execute("""
                        INSERT INTO omemo_device
                        (account_id, jid_id, device_id, identity_key, trust_level, first_seen, last_seen, label)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (self.account_id, jid_id, device_id, identity_key, trust_level, now, now, label))

            # Commit all changes to database
            self.db.commit()

            if self.logger:
                self.logger.debug(f"Updated device list for GUI: {len(devices)} OMEMO devices for {jid}")

        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to update OMEMO device list for {jid}: {e}")

    # =========================================================================
    # Future OMEMO Device Management (TODO)
    # =========================================================================

    async def fetch_device_list(self, jid: str):
        """
        Fetch OMEMO device list for a JID.

        Args:
            jid: JID to fetch devices for
        """
        # TODO: Extract from future implementation
        pass

    async def get_device_list(self, jid: str) -> list:
        """
        Get device list (fetch or from cache).

        Args:
            jid: JID to get devices for

        Returns:
            List of device IDs
        """
        # TODO: Extract device list retrieval logic
        pass

    async def trust_device(self, jid: str, device_id: int):
        """
        Trust an OMEMO device.

        Args:
            jid: JID owning the device
            device_id: Device ID to trust
        """
        # TODO: Extract trust management logic
        pass

    async def untrust_device(self, jid: str, device_id: int):
        """
        Untrust an OMEMO device.

        Args:
            jid: JID owning the device
            device_id: Device ID to untrust
        """
        # TODO: Extract untrust logic
        pass
