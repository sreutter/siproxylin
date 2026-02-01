"""
Fix for slixmpp XEP-0353 missing <finish> message support.

BUG DESCRIPTION:
Slixmpp's XEP-0353 (Jingle Message Initiation) plugin only supports 5 of the 6
message types defined in the specification. It handles <propose>, <retract>,
<accept>, <reject>, and <proceed>, but is missing <finish>.

The <finish> message is critical for multi-device scenarios - it's sent when a
call ends (either party hangs up) or when answered on another device.

SYMPTOMS:
1. Desktop receives incoming call (shows notification + dialog)
2. User answers call on phone
3. Phone sends <finish> message to desktop (via Message Carbons)
4. Desktop receives the XML but slixmpp doesn't recognize it
5. No event is fired, handler never called
6. Notification and dialog stay on screen until manually dismissed

ERROR IN LOGS:
No error - the <finish> message is silently ignored because slixmpp doesn't
have a Finish stanza class to parse it.

IMPACT:
- Incoming call notifications persist after answering on another device
- Creates UX confusion (user already answered, desktop still ringing)
- User must manually dismiss notification/dialog

ROOT CAUSE:
Two issues in slixmpp:

1. XEP-0353 plugin incomplete:
   - Defines 6 message types, but slixmpp only implements 5
   - Missing: Finish stanza class and handler
   - stanza.py: Only defines Propose, Retract, Accept, Proceed, Reject (NO Finish)
   - jingle_message.py: Only registers handlers for those 5

2. XEP-0280 carbon handlers don't check for <finish>:
   - When <finish> arrives in Message Carbon (from another device), it's wrapped
   - Carbon handlers extract forwarded message but don't check for finish
   - No jingle_message_finish event is fired for carboned messages

FIX:
Monkey-patch both plugins:

A. XEP_0353 plugin:
   1. Add a Finish stanza class
   2. Register it as a Message plugin
   3. Add a handler for incoming <finish> messages (direct)
   4. Emit 'jingle_message_finish' event

B. XEP_0280 carbon handlers:
   1. Patch _handle_carbon_received to check for <finish>
   2. Patch _handle_carbon_sent to check for <finish>
   3. Manually fire jingle_message_finish event for carboned finish messages

XMPP COMPLIANCE:
This fix implements XEP-0353 as specified. Per the spec (section 3.4):
- <finish> is sent when a call ends or is answered on another device
- It MUST be processed to properly handle multi-device scenarios

SLIXMPP ISSUE:
This is a missing feature in slixmpp's XEP-0353 implementation. The plugin
should support all 6 message types defined in the specification.

TODO WHEN SLIXMPP FIXES:
Simply remove this patch file and remove it from client.py imports.
Check slixmpp changelog for "XEP-0353 finish message support".
"""

import logging
from slixmpp.xmlstream import ElementBase, register_stanza_plugin
from slixmpp.xmlstream.handler import Callback
from slixmpp.xmlstream.matcher import StanzaPath
from slixmpp import Message

log = logging.getLogger(__name__)


# Define the Finish stanza class (following slixmpp's pattern)
class Finish(ElementBase):
    """
    <finish> stanza for XEP-0353 Jingle Message Initiation.

    Sent when a call ends (either party hangs up) or is answered on another device.
    """
    namespace = 'urn:xmpp:jingle-message:0'
    name = 'finish'
    plugin_attrib = 'jingle_finish'
    interfaces = {'id'}


def apply_patch():
    """Apply the XEP-0353 finish message support to slixmpp."""

    # ========================================================================
    # Part 1: Patch XEP-0353 plugin to add Finish stanza support
    # ========================================================================
    try:
        from slixmpp.plugins.xep_0353.jingle_message import XEP_0353
    except ImportError:
        log.warning("Could not import slixmpp XEP-0353 plugin, skipping patch")
        return

    # Store original plugin_init method
    original_plugin_init = XEP_0353.plugin_init

    def patched_plugin_init(self):
        """
        PATCHED: plugin_init that adds <finish> message support.

        Calls original plugin_init, then registers the Finish stanza and handler.
        """
        # Call original plugin_init (registers the other 5 message types)
        original_plugin_init(self)

        # Register Finish stanza as a Message plugin
        register_stanza_plugin(Message, Finish)

        # Register handler for incoming <finish> messages (direct, not carboned)
        self.xmpp.register_handler(
            Callback('Finishing a Session',
                StanzaPath('message/jingle_finish'),
                self._handle_finish))

        log.debug("Registered <finish> stanza and handler for XEP-0353")

    def _handle_finish(self, message):
        """
        Handle incoming <finish> message and emit jingle_message_finish event.

        This allows drunk_xmpp.calls.mixin to process the finish message and
        dismiss incoming call notifications when answered on another device.
        """
        self.xmpp.event('jingle_message_finish', message)

    # Apply the XEP-0353 patches
    XEP_0353.plugin_init = patched_plugin_init
    XEP_0353._handle_finish = _handle_finish

    log.debug("Applied XEP-0353 finish message patch (adds <finish> stanza support)")

    # ========================================================================
    # Part 2: Patch XEP-0280 carbon handlers to check for <finish>
    # ========================================================================
    try:
        from slixmpp.plugins.xep_0280.carbons import XEP_0280
    except ImportError:
        log.warning("Could not import slixmpp XEP-0280 plugin, skipping carbon patch")
        return

    # Store original carbon handler methods
    original_handle_carbon_received = XEP_0280._handle_carbon_received
    original_handle_carbon_sent = XEP_0280._handle_carbon_sent

    def patched_handle_carbon_received(self, msg):
        """
        PATCHED: Handle carbon_received messages and fire jingle message events.

        Original handler extracts forwarded message and fires 'carbon_received' event.
        This patch additionally checks for <accept> and <finish> and fires corresponding events.
        """
        # Call original handler first
        original_handle_carbon_received(self, msg)

        # Extract the forwarded message from carbon wrapper
        forwarded_msg = msg['carbon_received']
        if forwarded_msg is None:
            return

        # Check if forwarded message contains <accept> (XEP-0353)
        # When another device answers, it sends <accept> to bare JID (all devices)
        try:
            if forwarded_msg['jingle_accept']['id']:
                self.xmpp.event('jingle_message_accept', forwarded_msg)
                log.debug(f"Fired 'jingle_message_accept' event for carbon_received from {forwarded_msg['from']}")
        except (KeyError, TypeError):
            pass

        # Check if forwarded message contains <reject> (XEP-0353)
        # When another device rejects, it sends <reject> to caller (we get carbon)
        try:
            if forwarded_msg['jingle_reject']['id']:
                self.xmpp.event('jingle_message_reject', forwarded_msg)
                log.debug(f"Fired 'jingle_message_reject' event for carbon_received from {forwarded_msg['from']}")
        except (KeyError, TypeError):
            pass

        # Check if forwarded message contains <finish> (XEP-0353)
        try:
            if forwarded_msg['jingle_finish']['id']:
                self.xmpp.event('jingle_message_finish', forwarded_msg)
                log.debug(f"Fired 'jingle_message_finish' event for carbon_received from {forwarded_msg['from']}")
        except (KeyError, TypeError):
            pass

    def patched_handle_carbon_sent(self, msg):
        """
        PATCHED: Handle carbon_sent messages and fire jingle message events.

        Original handler extracts forwarded message and fires 'carbon_sent' event.
        This patch additionally checks for <accept> and <finish> and fires corresponding events.
        """
        # Call original handler first
        original_handle_carbon_sent(self, msg)

        # Extract the forwarded message from carbon wrapper
        forwarded_msg = msg['carbon_sent']
        if forwarded_msg is None:
            return

        # Check if forwarded message contains <accept> (XEP-0353)
        # When another device answers, it sends <accept> to bare JID (all devices)
        try:
            if forwarded_msg['jingle_accept']['id']:
                self.xmpp.event('jingle_message_accept', forwarded_msg)
                log.debug(f"Fired 'jingle_message_accept' event for carbon_sent to {forwarded_msg['to']}")
        except (KeyError, TypeError):
            pass

        # Check if forwarded message contains <reject> (XEP-0353)
        # When another device rejects, it sends <reject> to caller (we get carbon)
        try:
            if forwarded_msg['jingle_reject']['id']:
                self.xmpp.event('jingle_message_reject', forwarded_msg)
                log.debug(f"Fired 'jingle_message_reject' event for carbon_sent to {forwarded_msg['to']}")
        except (KeyError, TypeError):
            pass

        # Check if forwarded message contains <finish> (XEP-0353)
        try:
            if forwarded_msg['jingle_finish']['id']:
                self.xmpp.event('jingle_message_finish', forwarded_msg)
                log.debug(f"Fired 'jingle_message_finish' event for carbon_sent to {forwarded_msg['to']}")
        except (KeyError, TypeError):
            pass

    # Apply the XEP-0280 patches
    XEP_0280._handle_carbon_received = patched_handle_carbon_received
    XEP_0280._handle_carbon_sent = patched_handle_carbon_sent

    log.debug("Applied XEP-0280 carbon finish message patch (fires finish events for carbons)")
