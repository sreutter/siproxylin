"""
Messaging features module for DrunkXMPP.

XEP-0085: Chat State Notifications (typing indicators)
XEP-0184: Message Delivery Receipts
XEP-0333: Chat Markers (read receipts)

Provides methods for sending chat states, delivery receipts, and read markers.
"""

from slixmpp.jid import JID


class MessagingMixin:
    """
    Mixin providing messaging feature support.

    Requirements (provided by DrunkXMPP):
    - self.plugin: Dict of loaded slixmpp plugins
    - self.make_message(): Method to create message stanzas
    - self.logger: Logger instance
    """

    # ============================================================================
    # XEP-0085: Chat State Notifications
    # ============================================================================

    def send_chat_state(self, jid: str, state: str):
        """
        Send a chat state notification (typing indicator).

        Args:
            jid: Recipient JID
            state: Chat state - one of: 'active', 'composing', 'paused', 'inactive', 'gone'

        States:
            - active: User is actively participating in the chat
            - composing: User is typing
            - paused: User stopped typing but chat is still focused
            - inactive: User has not been active for a while
            - gone: User has closed the chat window
        """
        valid_states = ['active', 'composing', 'paused', 'inactive', 'gone']
        if state not in valid_states:
            raise ValueError(f"Invalid chat state: {state}. Must be one of {valid_states}")

        # Determine message type based on whether this is a MUC
        msg_type = 'groupchat' if jid in self.joined_rooms else 'chat'

        msg = self.make_message(mto=jid, mtype=msg_type)
        msg['chat_state'] = state
        msg.send()

        self.logger.debug(f"Sent chat state '{state}' to {jid} (type={msg_type})")

    # ============================================================================
    # XEP-0184: Message Delivery Receipts
    # ============================================================================

    def send_receipt(self, jid: str, message_id: str):
        """
        Send a delivery receipt for a received message.

        Args:
            jid: JID of the message sender
            message_id: ID of the message to acknowledge
        """
        xep_0184 = self.plugin['xep_0184']

        # Determine message type based on whether this is a MUC
        msg_type = 'groupchat' if jid in self.joined_rooms else 'chat'

        ack = self.make_message(mto=jid, mtype=msg_type)
        ack['receipt'] = message_id
        ack.send()

        self.logger.debug(f"Sent delivery receipt to {jid} for message {message_id} (type={msg_type})")

    # ============================================================================
    # XEP-0333: Chat Markers
    # ============================================================================

    def send_marker(self, jid: str, message_id: str, marker: str):
        """
        Send a chat marker (read receipt).

        Args:
            jid: Recipient JID
            message_id: ID of the message being marked
            marker: Marker type - one of: 'received', 'displayed', 'acknowledged'

        Markers:
            - received: Message has been received by the client
            - displayed: Message has been displayed to the user
            - acknowledged: Message has been acknowledged by the user (e.g., read)
        """
        valid_markers = ['received', 'displayed', 'acknowledged']
        if marker not in valid_markers:
            raise ValueError(f"Invalid marker: {marker}. Must be one of {valid_markers}")

        # Determine message type based on whether this is a MUC
        msg_type = 'groupchat' if jid in self.joined_rooms else 'chat'

        # Build marker message manually to ensure correct type for MUCs
        msg = self.make_message(mto=jid, mtype=msg_type)
        msg[marker]['id'] = message_id
        msg.send()

        self.logger.debug(f"Sent '{marker}' marker to {jid} for message {message_id} (type={msg_type})")
