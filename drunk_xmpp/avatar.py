"""
Avatar support mixin for DrunkXMPP.

Implements:
- XEP-0054: vcard-temp (base vCard functionality)
- XEP-0084: User Avatar (modern PEP-based avatars)
- XEP-0153: vCard-Based Avatars (legacy presence-based avatars)

Strategy:
- Try XEP-0084 first (modern, efficient)
- Fallback to XEP-0153/0054 (legacy, compatible)
- Cache avatars to avoid redundant fetches
- Notify callback when avatar is fetched
"""

import hashlib
import logging
from typing import Optional, Callable, Dict
from slixmpp.exceptions import IqError, IqTimeout


class AvatarMixin:
    """
    Mixin for avatar fetching and management.

    Provides methods to:
    - Fetch avatars from contacts (XEP-0084 PEP or XEP-0153 vCard)
    - Publish own avatar
    - Handle avatar update notifications
    """

    def _init_avatar_cache(self):
        """Initialize avatar cache if not already initialized."""
        if not hasattr(self, 'avatar_cache'):
            self.avatar_cache: Dict[str, Dict] = {}
        if not hasattr(self, 'on_avatar_update_callback'):
            self.on_avatar_update_callback: Optional[Callable] = None

    async def get_avatar(self, jid: str, prefer_pep: bool = True) -> Optional[Dict]:
        """
        Fetch avatar for a JID.

        Tries XEP-0084 (PEP) first, falls back to XEP-0153/0054 (vCard).

        Args:
            jid: Bare JID of the entity
            prefer_pep: Try PEP first (default True)

        Returns:
            Dict with keys: 'data' (bytes), 'hash' (str), 'mime_type' (str), 'source' (str)
            None if no avatar found or error
        """
        # Initialize cache if needed
        self._init_avatar_cache()

        # Check cache first
        if jid in self.avatar_cache:
            self.logger.debug(f"Avatar cache hit for {jid}")
            return self.avatar_cache[jid]

        avatar_data = None

        if prefer_pep:
            # Try XEP-0084 (modern PEP-based) first
            avatar_data = await self._get_avatar_pep(jid)

            # Fallback to vCard if PEP fails
            if not avatar_data:
                self.logger.debug(f"PEP avatar not available for {jid}, trying vCard")
                avatar_data = await self._get_avatar_vcard(jid)
        else:
            # Try vCard first
            avatar_data = await self._get_avatar_vcard(jid)

            # Fallback to PEP if vCard fails
            if not avatar_data:
                self.logger.debug(f"vCard avatar not available for {jid}, trying PEP")
                avatar_data = await self._get_avatar_pep(jid)

        # Cache if found
        if avatar_data:
            self.avatar_cache[jid] = avatar_data
            self.logger.info(f"Avatar fetched for {jid} from {avatar_data['source']}")

            # Notify callback
            if self.on_avatar_update_callback:
                try:
                    await self.on_avatar_update_callback(jid, avatar_data)
                except Exception as e:
                    self.logger.exception(f"Error in avatar update callback: {e}")

        return avatar_data

    async def _get_avatar_pep(self, jid: str) -> Optional[Dict]:
        """
        Fetch avatar using XEP-0084 (PEP).

        Args:
            jid: Bare JID

        Returns:
            Dict with avatar data or None
        """
        try:
            from slixmpp.jid import JID

            # Use xep_0060 (PubSub) to get metadata
            # XEP-0084 uses PubSub nodes: urn:xmpp:avatar:metadata and urn:xmpp:avatar:data
            metadata_namespace = 'urn:xmpp:avatar:metadata'
            data_namespace = 'urn:xmpp:avatar:data'

            # Get metadata items from the PubSub node
            metadata_result = await self.plugin['xep_0060'].get_items(
                JID(jid),
                metadata_namespace,
                max_items=1,
                timeout=10
            )

            # Extract items - this is an ElementBase, not a list
            items_element = metadata_result['pubsub']['items']

            # Iterate over Item children (registered as iterable)
            item_list = list(items_element)
            if not item_list:
                self.logger.debug(f"No PEP avatar metadata items for {jid}")
                return None

            # Get the first (most recent) metadata item payload
            first_item = item_list[0]
            metadata_payload = first_item['payload']

            # Find the best avatar info (prefer PNG, then any available)
            avatar_info = None
            for info in metadata_payload.findall('{urn:xmpp:avatar:metadata}info'):
                mime_type = info.get('type', '')
                if mime_type == 'image/png':
                    avatar_info = info
                    break
                elif not avatar_info:
                    avatar_info = info

            if not avatar_info:
                self.logger.debug(f"No avatar info in metadata for {jid}")
                return None

            avatar_id = avatar_info.get('id')
            mime_type = avatar_info.get('type', 'image/png')

            if not avatar_id:
                self.logger.debug(f"No avatar ID in metadata for {jid}")
                return None

            # Fetch the actual avatar data using XEP-0084's retrieve_avatar method
            data_result = await self.plugin['xep_0084'].retrieve_avatar(JID(jid), avatar_id, timeout=10)

            # Extract base64 data from result - items is ElementBase, not list
            items_element = data_result['pubsub']['items']
            self.logger.debug(f"Avatar data fetch for {jid}: items_element type={type(items_element).__name__}")

            # Iterate over Item children (registered as iterable)
            item_list = list(items_element)
            self.logger.debug(f"Avatar data fetch for {jid}: item_list length={len(item_list)}")
            if not item_list:
                self.logger.debug(f"No avatar data items for {jid}")
                return None

            first_item = item_list[0]
            self.logger.debug(f"Avatar data fetch for {jid}: first_item type={type(first_item).__name__}")
            data_payload = first_item['payload']
            self.logger.debug(f"Avatar data fetch for {jid}: payload type={type(data_payload).__name__}, "
                             f"has xml.text={hasattr(data_payload, 'xml') and hasattr(data_payload.xml, 'text')}")

            # The payload is a Data element with base64 encoded image
            import base64
            if hasattr(data_payload, 'xml') and hasattr(data_payload.xml, 'text'):
                base64_text = data_payload.xml.text.strip()
                self.logger.debug(f"Avatar data fetch for {jid}: base64 length={len(base64_text)}")
                data = base64.b64decode(base64_text)
            else:
                self.logger.error(f"Avatar data payload has no xml.text for {jid}")
                return None

            # Calculate hash for verification
            sha1_hash = hashlib.sha1(data).hexdigest()

            self.logger.debug(f"PEP avatar fetched for {jid}: {len(data)} bytes, hash={sha1_hash}")

            return {
                'data': data,
                'hash': sha1_hash,
                'mime_type': mime_type,
                'source': 'xep_0084'
            }

        except (IqError, IqTimeout) as e:
            self.logger.debug(f"Failed to fetch PEP avatar for {jid}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching PEP avatar for {jid}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    async def _get_avatar_vcard(self, jid: str) -> Optional[Dict]:
        """
        Fetch avatar using XEP-0054 (vCard-temp).

        Args:
            jid: Bare JID

        Returns:
            Dict with avatar data or None
        """
        try:
            from slixmpp.jid import JID

            # Fetch vCard
            vcard_iq = await self.plugin['xep_0054'].get_vcard(JID(jid), timeout=10)

            if not vcard_iq:
                self.logger.debug(f"No vCard IQ response for {jid}")
                return None

            # Extract vCard stanza element from IQ
            vcard = vcard_iq['vcard_temp']

            # Access PHOTO using slixmpp's vCard interface
            # The vcard_temp stanza has properties like 'PHOTO', 'FN', etc.
            if not vcard['PHOTO']:
                self.logger.debug(f"No PHOTO in vCard for {jid}")
                return None

            # Get BINVAL (image bytes) or EXTVAL (URL)
            # slixmpp's vcard_temp plugin already decodes BINVAL from base64 to bytes
            binval = vcard['PHOTO']['BINVAL']
            extval = vcard['PHOTO']['EXTVAL']

            if not binval and not extval:
                self.logger.debug(f"No BINVAL or EXTVAL in vCard PHOTO for {jid}")
                return None

            mime_type = vcard['PHOTO']['TYPE'] or 'image/png'

            # Use BINVAL directly (already decoded by slixmpp)
            if binval:
                # BINVAL is already bytes, no need to base64 decode
                data = binval
            elif extval:
                # EXTVAL contains URL - need to download
                self.logger.debug(f"vCard has EXTVAL (URL) for {jid}: {extval}")
                self.logger.warning(f"HTTP download from EXTVAL not yet implemented - avatar will not be available")
                return None
            else:
                return None

            # Calculate hash
            sha1_hash = hashlib.sha1(data).hexdigest()

            self.logger.debug(f"vCard avatar fetched for {jid}: {len(data)} bytes, hash={sha1_hash}")

            return {
                'data': data,
                'hash': sha1_hash,
                'mime_type': mime_type,
                'source': 'xep_0054'
            }

        except (IqError, IqTimeout) as e:
            self.logger.debug(f"Failed to fetch vCard avatar for {jid}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error fetching vCard avatar for {jid}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return None

    def get_cached_avatar(self, jid: str) -> Optional[Dict]:
        """
        Get avatar from cache without fetching.

        Args:
            jid: Bare JID

        Returns:
            Cached avatar dict or None
        """
        self._init_avatar_cache()
        return self.avatar_cache.get(jid)

    def clear_avatar_cache(self, jid: Optional[str] = None):
        """
        Clear avatar cache.

        Args:
            jid: If provided, clear only this JID. Otherwise clear all.
        """
        self._init_avatar_cache()
        if jid:
            if jid in self.avatar_cache:
                del self.avatar_cache[jid]
                self.logger.debug(f"Cleared avatar cache for {jid}")
        else:
            self.avatar_cache.clear()
            self.logger.debug("Cleared all avatar cache")
