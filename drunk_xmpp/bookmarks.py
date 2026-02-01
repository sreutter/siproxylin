"""
Bookmarks module for DrunkXMPP.

XEP-0402: PEP Native Bookmarks

Provides methods for managing server-side MUC room bookmarks.
"""

from typing import List, Dict, Any, Optional
from slixmpp.exceptions import IqError


class BookmarksMixin:
    """
    Mixin providing bookmarks management functionality.

    Requirements (provided by DrunkXMPP):
    - self.plugin: Dict of loaded slixmpp plugins
    - self.boundjid: Current bound JID
    - self.logger: Logger instance
    """

    # ============================================================================
    # XEP-0402: PEP Native Bookmarks
    # ============================================================================

    async def get_bookmarks(self) -> List[Dict[str, Any]]:
        """
        Retrieve bookmarks from server using PEP Native Bookmarks (XEP-0402).

        Returns:
            List of bookmark dicts with keys:
            - jid: Room JID
            - name: Bookmark name
            - nick: Nickname to use
            - password: Room password (if any)
            - autojoin: Boolean indicating if room should be auto-joined
        """
        try:
            xep_0060 = self.plugin['xep_0060']

            # Retrieve bookmarks from PEP node
            # For PEP, jid is our own bare JID, node is the bookmarks namespace
            result = await xep_0060.get_items(
                jid=self.boundjid.bare,
                node='urn:xmpp:bookmarks:1',
                timeout=10
            )

            bookmarks = []
            for item in result['pubsub']['items']:
                conf = item['conference']
                if conf:
                    bookmarks.append({
                        'jid': item['id'],  # Item ID is the room JID
                        'name': conf.get('name', ''),
                        'nick': conf.get('nick', ''),
                        'password': conf.get('password', ''),
                        'autojoin': conf.get('autojoin', False)
                    })

            self.logger.info(f"Retrieved {len(bookmarks)} bookmarks")
            return bookmarks

        except IqError as e:
            # Node might not exist yet (no bookmarks)
            if e.iq['error']['condition'] == 'item-not-found':
                self.logger.info("No bookmarks found (node doesn't exist)")
                return []
            self.logger.warning(f"Failed to retrieve bookmarks: {e.iq['error']['condition']}")
            return []
        except Exception as e:
            self.logger.exception(f"Failed to retrieve bookmarks: {e}")
            return []

    async def add_bookmark(self, jid: str, name: str, nick: str,
                          password: Optional[str] = None, autojoin: bool = True):
        """
        Add or update a bookmark on the server.

        Args:
            jid: Room JID to bookmark
            name: Display name for the bookmark
            nick: Nickname to use in the room
            password: Optional room password
            autojoin: Whether to auto-join this room on login (default: True)
        """
        try:
            xep_0060 = self.plugin['xep_0060']

            # Create conference element
            from slixmpp.plugins.xep_0402.stanza import Conference

            conf = Conference()
            conf['name'] = name
            conf['autojoin'] = autojoin
            if nick:
                conf['nick'] = nick
            if password:
                conf['password'] = password

            # Publish to bookmarks node
            await xep_0060.publish(
                jid=self.boundjid.bare,
                node='urn:xmpp:bookmarks:1',
                id=jid,
                payload=conf,
                timeout=10
            )

            self.logger.info(f"Added/updated bookmark: {jid} (autojoin={autojoin})")

        except IqError as e:
            error_condition = e.iq['error']['condition']
            self.logger.warning(f"Failed to add bookmark: {error_condition}")
            raise
        except Exception as e:
            self.logger.exception(f"Failed to add bookmark: {e}")
            raise

    async def remove_bookmark(self, jid: str):
        """
        Remove a bookmark from the server.

        Args:
            jid: Room JID to remove from bookmarks
        """
        try:
            xep_0060 = self.plugin['xep_0060']

            # Delete item from bookmarks node
            await xep_0060.retract(
                jid=self.boundjid.bare,
                node='urn:xmpp:bookmarks:1',
                id=jid,
                timeout=10
            )

            self.logger.info(f"Removed bookmark: {jid}")

        except IqError as e:
            error_condition = e.iq['error']['condition']
            self.logger.warning(f"Failed to remove bookmark: {error_condition}")
            raise
        except Exception as e:
            self.logger.exception(f"Failed to remove bookmark: {e}")
            raise
