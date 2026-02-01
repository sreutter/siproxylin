"""
XEP-0221 Media Element utilities for data forms (including XEP-0158 CAPTCHA support)

Provides generic utilities for extracting media from XEP-0004 data form fields.
Works with XEP-0221 (Media Elements) and XEP-0231 (Bits of Binary).

Generic implementation - we don't try to detect CAPTCHA specifically, just extract
media from any form field that has it.

Usage:
    from drunk_xmpp import xep_0158

    # Extract media from any form field
    media = xep_0158.extract_field_media(field)

    # Extract BoB data from parent IQ
    bob_data = xep_0158.extract_bob_from_iq(iq)
"""

import logging
import base64
from typing import Dict, Any, Optional

logger = logging.getLogger('drunk-xmpp.xep-0158')


# Namespace constants
MEDIA_NAMESPACE = "urn:xmpp:media-element"
BOB_NAMESPACE = "urn:xmpp:bob"


def extract_field_media(field) -> Optional[Dict[str, Any]]:
    """
    Extract media element from a form field (XEP-0221 / XEP-0231).

    Args:
        field: slixmpp FormField object

    Returns:
        dict: {
            'type': 'url' or 'bob',
            'mime_type': str,              # e.g., 'image/png'
            'data': str,                   # URL or CID
            'alt': str or None,            # Alt text
            'width': int or None,
            'height': int or None,
            'uris': list                   # All available URIs (XEP-0221)
        }
        Returns None if no media found
    """
    try:
        # Check if field has media sub-element (XEP-0221)
        # Need to access the underlying XML element
        media = field.get('media')
        if not media:
            logger.debug(f"Field {field.get('var')} has no media element")
            return None

        result = {
            'type': None,
            'mime_type': None,
            'data': None,
            'alt': None,
            'width': None,
            'height': None,
            'uris': []
        }

        # Access the XML element from slixmpp object
        media_xml = media.xml if hasattr(media, 'xml') else media

        # Extract attributes
        result['alt'] = media_xml.get('alt')
        result['width'] = media_xml.get('width')
        result['height'] = media_xml.get('height')

        # Extract all URIs from media element
        uris = media_xml.findall(f'{{{MEDIA_NAMESPACE}}}uri')

        for uri_elem in uris:
            uri_type = uri_elem.get('type', '')  # MIME type
            uri_value = uri_elem.text or ''

            result['uris'].append({
                'type': uri_type,
                'value': uri_value
            })

            # Prefer first URI for primary data
            if not result['mime_type']:
                result['mime_type'] = uri_type

                # Check if it's a cid: URI (XEP-0231 BoB)
                if uri_value.startswith('cid:'):
                    result['type'] = 'bob'
                    result['data'] = uri_value  # Store CID, will fetch later
                    logger.debug(f"Found BoB media: cid={uri_value}")

                # HTTP/HTTPS URL
                elif uri_value.startswith('http://') or uri_value.startswith('https://'):
                    result['type'] = 'url'
                    result['data'] = uri_value
                    logger.debug(f"Found URL media: {uri_value}")

                else:
                    logger.warning(f"Unknown URI scheme: {uri_value}")

        if result['type']:
            return result
        else:
            logger.debug("No usable media URIs found")
            return None

    except Exception as e:
        logger.error(f"Failed to extract field media: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


def extract_bob_from_iq(iq) -> Optional[Dict[str, bytes]]:
    """
    Extract Bits of Binary (XEP-0231) data from IQ stanza.

    Args:
        iq: slixmpp IQ stanza containing bob elements

    Returns:
        dict: {cid: {'data': bytes, 'mime_type': str}, ...}
        Returns None if no BoB data found
    """
    try:
        bob_data = {}

        # Access underlying XML element from slixmpp IQ stanza
        iq_xml = iq.xml if hasattr(iq, 'xml') else iq

        # Find all <data xmlns='urn:xmpp:bob'> elements
        bob_elements = iq_xml.findall(f'.//{{{BOB_NAMESPACE}}}data')

        for bob_elem in bob_elements:
            cid = bob_elem.get('cid', '')
            mime_type = bob_elem.get('type', '')
            encoded_data = bob_elem.text or ''

            if cid and encoded_data:
                # Decode base64 data
                try:
                    decoded_data = base64.b64decode(encoded_data)
                    bob_data[cid] = {
                        'data': decoded_data,
                        'mime_type': mime_type
                    }
                    logger.debug(f"Extracted BoB data: cid={cid}, "
                               f"mime_type={mime_type}, size={len(decoded_data)} bytes")
                except Exception as decode_err:
                    logger.error(f"Failed to decode BoB data for cid={cid}: {decode_err}")

        return bob_data if bob_data else None

    except Exception as e:
        logger.error(f"Failed to extract BoB from IQ: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None


__all__ = [
    'extract_field_media',
    'extract_bob_from_iq',
    'MEDIA_NAMESPACE',
    'BOB_NAMESPACE'
]
