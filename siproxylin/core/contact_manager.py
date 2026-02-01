"""
Contact/Roster manager for DRUNK-XMPP-GUI.

Handles roster operations: adding, removing, blocking contacts.
Delegates XEP-0191 (Blocking Command) to DrunkXMPP client.
"""

import logging
from typing import Optional

from ..db.database import get_db


logger = logging.getLogger('siproxylin.contact_manager')


class ContactManager:
    """
    Manages contact roster operations.
    """

    def __init__(self):
        """Initialize contact manager."""
        self.db = get_db()
        logger.info("Contact manager initialized")

    async def add_contact(self, account_id: int, xmpp_client, jid: str, name: str = None,
                         send_subscription: bool = True):
        """
        Add a contact to roster and optionally send subscription request.

        Args:
            account_id: Account ID
            xmpp_client: DrunkXMPP client instance
            jid: Contact JID
            name: Display name (optional)
            send_subscription: Send subscription request for presence
        """
        if not xmpp_client:
            raise RuntimeError("XMPP client not connected")

        logger.info(f"Adding contact {jid} for account {account_id} (name={name}, sub={send_subscription})")

        try:
            if send_subscription:
                # Send presence subscription request
                xmpp_client.send_presence_subscription(pto=jid, ptype='subscribe', pnick=name)
                logger.info(f"Subscription request sent to {jid}")

            # Roster entry is created automatically when subscription is accepted
            # or can be added manually to roster table

        except Exception as e:
            logger.error(f"Failed to add contact {jid}: {e}")
            raise

    async def remove_contact(self, account_id: int, xmpp_client, jid: str):
        """
        Remove a contact from roster and revoke subscriptions.

        Args:
            account_id: Account ID
            xmpp_client: DrunkXMPP client instance
            jid: Contact JID
        """
        if not xmpp_client:
            raise RuntimeError("XMPP client not connected")

        logger.info(f"Removing contact {jid} for account {account_id}")

        try:
            # Unsubscribe from presence (both directions)
            xmpp_client.send_presence_subscription(pto=jid, ptype='unsubscribe')
            xmpp_client.send_presence_subscription(pto=jid, ptype='unsubscribed')

            # Remove from roster
            xmpp_client.client_roster.remove(jid)

            logger.info(f"Contact {jid} removed from roster")

        except Exception as e:
            logger.error(f"Failed to remove contact {jid}: {e}")
            raise

    async def block_contact(self, account_id: int, xmpp_client, jid: str):
        """
        Block a contact using XEP-0191 (Blocking Command).
        Delegates to DrunkXMPP client's block_contact() method.

        Args:
            account_id: Account ID
            xmpp_client: DrunkXMPP client instance
            jid: Contact JID
        """
        if not xmpp_client:
            raise RuntimeError("XMPP client not connected")

        logger.info(f"Blocking contact {jid} for account {account_id}")

        try:
            # Use DrunkXMPP's XEP-0191 implementation (uses slixmpp plugin)
            success = await xmpp_client.block_contact(jid)

            if not success:
                raise RuntimeError(f"Failed to block {jid} - server returned error")

            logger.info(f"Contact {jid} blocked successfully")

        except Exception as e:
            logger.error(f"Failed to block contact {jid}: {e}")
            raise

    async def unblock_contact(self, account_id: int, xmpp_client, jid: str):
        """
        Unblock a contact using XEP-0191 (Blocking Command).
        Delegates to DrunkXMPP client's unblock_contact() method.

        Args:
            account_id: Account ID
            xmpp_client: DrunkXMPP client instance
            jid: Contact JID
        """
        if not xmpp_client:
            raise RuntimeError("XMPP client not connected")

        logger.info(f"Unblocking contact {jid} for account {account_id}")

        try:
            # Use DrunkXMPP's XEP-0191 implementation (uses slixmpp plugin)
            success = await xmpp_client.unblock_contact(jid)

            if not success:
                raise RuntimeError(f"Failed to unblock {jid} - server returned error")

            logger.info(f"Contact {jid} unblocked successfully")

        except Exception as e:
            logger.error(f"Failed to unblock contact {jid}: {e}")
            raise

    async def update_contact_name(self, account_id: int, xmpp_client, jid: str, name: str):
        """
        Update contact display name in roster.

        Args:
            account_id: Account ID
            xmpp_client: DrunkXMPP client instance
            jid: Contact JID
            name: New display name
        """
        if not xmpp_client:
            raise RuntimeError("XMPP client not connected")

        logger.info(f"Updating name for contact {jid} to '{name}' for account {account_id}")

        try:
            # Update roster item with new name
            xmpp_client.update_roster(jid, name=name)

            logger.info(f"Contact {jid} name updated to '{name}'")

        except Exception as e:
            logger.error(f"Failed to update contact {jid} name: {e}")
            raise


# Global contact manager instance
_contact_manager: Optional[ContactManager] = None


def get_contact_manager() -> ContactManager:
    """
    Get global contact manager instance.

    Returns:
        ContactManager instance
    """
    global _contact_manager
    if _contact_manager is None:
        _contact_manager = ContactManager()
    return _contact_manager
