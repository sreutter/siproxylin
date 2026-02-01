"""
Fix for slixmpp XEP-0280 carbons not firing reaction events.

BUG DESCRIPTION:
When carbon copies (XEP-0280) contain reactions (XEP-0444), slixmpp does not fire
the 'reactions' event. The carbon handlers in XEP-0280 extract and forward the
wrapped message, but slixmpp's reaction plugin doesn't register handlers for carbon
events, so reactions in carbons are silently ignored.

SYMPTOMS:
1. Send message from phone (appears in desktop as carbon)
2. React to message from phone
3. Reaction carbon arrives at desktop
4. Desktop never processes the reaction → no reaction shown in UI

ERROR IN LOGS:
No error - the reaction is silently dropped because no handler processes it.

IMPACT:
- Reactions on carbon copy messages never appear
- Creates UX confusion (reactions work on some messages but not others)
- User has no idea why reactions aren't syncing

ROOT CAUSE:
XEP-0280 carbon handlers (_handle_carbon_received/_handle_carbon_sent) extract
the forwarded message and dispatch it as a regular message. However, slixmpp's
reaction plugin (XEP-0444) doesn't register for 'carbon_received' or 'carbon_sent'
events - it only handles regular 'message' events.

The carbon plugin fires these events with the wrapper message, but doesn't check
if the forwarded message contains reactions and manually trigger the reaction event.

FIX:
Patch the carbon handlers to check for reactions in forwarded messages and
manually fire the 'reactions' event, just like they do for regular messages.

XMPP COMPLIANCE:
This fix does not violate any XEP. Per XEP-0280:
- Carbon copies contain forwarded messages that should be processed identically
- All extensions (reactions, corrections, etc.) in forwarded messages should work

Per XEP-0444:
- Reactions can be sent in any message type (including carbons)
- Clients should process reactions regardless of delivery mechanism

SLIXMPP ISSUE:
This appears to be an oversight in slixmpp's XEP-0280 plugin. It should handle
all message extensions (reactions, corrections, etc.) in carbon copies.

TODO WHEN SLIXMPP FIXES:
Simply remove this patch file and remove it from __init__.py apply_all_patches()
"""

import logging

log = logging.getLogger(__name__)


def apply_patch():
    """Apply the XEP-0280 carbon reactions fix to slixmpp."""
    try:
        from slixmpp.plugins.xep_0280.carbons import XEP_0280
    except ImportError:
        log.warning("Could not import slixmpp XEP-0280 plugin, skipping patch")
        return

    # Store original methods
    original_handle_carbon_received = XEP_0280._handle_carbon_received
    original_handle_carbon_sent = XEP_0280._handle_carbon_sent

    def patched_handle_carbon_received(self, msg):
        """
        PATCHED: Handle carbon_received messages and fire reaction events.

        Original handler extracts forwarded message and fires 'carbon_received' event.
        This patch additionally checks for reactions and fires 'reactions' event.
        """
        # Call original handler first
        original_handle_carbon_received(self, msg)

        # Extract the forwarded message from carbon wrapper
        forwarded_msg = msg['carbon_received']
        if forwarded_msg is None:
            return

        # Check if forwarded message contains reactions (XEP-0444)
        try:
            if forwarded_msg['reactions']['id']:
                # Manually fire the 'reactions' event that slixmpp normally fires for regular messages
                # The reaction plugin's handler will process it
                self.xmpp.event('reactions', forwarded_msg)
                log.debug(f"Fired 'reactions' event for carbon_received from {forwarded_msg['from']}")
        except (KeyError, TypeError):
            # No reactions in this carbon, that's fine
            pass

    def patched_handle_carbon_sent(self, msg):
        """
        PATCHED: Handle carbon_sent messages and fire reaction events.

        Original handler extracts forwarded message and fires 'carbon_sent' event.
        This patch additionally checks for reactions and fires 'reactions' event.
        """
        # Call original handler first
        original_handle_carbon_sent(self, msg)

        # Extract the forwarded message from carbon wrapper
        forwarded_msg = msg['carbon_sent']
        if forwarded_msg is None:
            return

        # Check if forwarded message contains reactions (XEP-0444)
        try:
            if forwarded_msg['reactions']['id']:
                # Manually fire the 'reactions' event that slixmpp normally fires for regular messages
                # The reaction plugin's handler will process it
                self.xmpp.event('reactions', forwarded_msg)
                log.debug(f"Fired 'reactions' event for carbon_sent to {forwarded_msg['to']}")
        except (KeyError, TypeError):
            # No reactions in this carbon, that's fine
            pass

    # Apply the patches
    XEP_0280._handle_carbon_received = patched_handle_carbon_received
    XEP_0280._handle_carbon_sent = patched_handle_carbon_sent
    log.debug("Applied XEP-0280 carbon reactions fix (fires reaction events for carbons)")
