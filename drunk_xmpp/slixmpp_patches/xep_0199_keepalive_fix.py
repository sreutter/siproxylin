"""
Fix for slixmpp XEP-0199 keepalive bug with XEP-0198 stream management.

BUG DESCRIPTION:
When keepalive: True is set in XEP-0199 plugin config, slixmpp registers
enable_keepalive() as an event handler for 'session_start' and 'session_resumed'.
Event handlers receive event stanzas as their first parameter, but enable_keepalive()
expects float parameters (interval, timeout). This causes TypeError when session_resumed
fires after XEP-0198 stream resumption.

ERROR:
    TypeError: unsupported operand type(s) for +: 'float' and 'Iq'
    at asyncio/base_events.py:727 in call_later
    when trying to schedule the next keepalive ping

IMPACT:
- Keepalive works on initial session_start
- Keepalive FAILS on session_resumed (XEP-0198)
- No more pings sent after reconnection
- Connection failures won't be detected

FIX:
Make enable_keepalive() detect when it's called as an event handler (first param
is a stanza with 'xml' attribute) and ignore that parameter, using configured values.

XMPP COMPLIANCE:
This fix does not violate any XEP. XEP-0198 and XEP-0199 are complementary:
- XEP-0199: Detects broken connections via keepalive pings
- XEP-0198: Resumes sessions after reconnection
Both should work together as per XEP-0198 recommendation to use XEP-0199 for connection detection.

SUBMITTED UPSTREAM:
[TODO: Add issue/PR link when submitted]
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)


def apply_patch():
    """Apply the XEP-0199 keepalive fix to slixmpp."""
    try:
        from slixmpp.plugins.xep_0199.ping import XEP_0199
    except ImportError:
        log.warning("Could not import slixmpp XEP-0199 plugin, skipping patch")
        return

    # Store original method
    original_enable_keepalive = XEP_0199.enable_keepalive

    def patched_enable_keepalive(self, interval: Optional[float] = None,
                                  timeout: Optional[float] = None) -> None:
        """
        Enable the ping keepalive on the connection.
        The plugin will send a ping at `interval` and reconnect if the ping timeouts.

        :param interval: The interval between each ping (or event stanza when called as event handler)
        :param timeout: The timeout of the ping

        PATCHED: Handles being called as an event handler where interval is an Iq stanza.
        """
        # Handle being called as an event handler (interval will be an event stanza)
        # When registered via add_event_handler(), slixmpp passes event data as first param
        # Event stanzas have an 'xml' attribute, floats/None don't
        if interval is not None and hasattr(interval, 'xml'):
            # Called as event handler, ignore the stanza parameter and use configured values
            interval = None
            timeout = None

        # Call original method with cleaned parameters
        return original_enable_keepalive(self, interval, timeout)

    # Apply the patch
    XEP_0199.enable_keepalive = patched_enable_keepalive
    log.debug("Applied XEP-0199 keepalive fix for XEP-0198 compatibility")
