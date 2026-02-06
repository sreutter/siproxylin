"""
Add room membership request support to slixmpp XEP-0045.

FEATURE ADDITION (not a bug fix):
slixmpp's XEP-0045 plugin provides request_voice() for moderated rooms but
does not provide a method to request membership in members-only rooms.

PROTOCOL:
Per XEP-0045 §7.10 and XEP-0077, users can register with a room to gain
membership status using in-band registration (jabber:iq:register namespace):

1. Client sends IQ-get to room with <query xmlns='jabber:iq:register'/>
2. Room responds with registration form (XEP-0004 data form)
3. Client submits IQ-set with filled form (typically nickname + optional reason)
4. Room responds with IQ-result (success) or IQ-error (rejected)

IMPLEMENTATION:
Adds async method request_room_membership(room, reason) to XEP_0045 class.
Uses XEP-0077 in-band registration protocol to request membership.

XMPP COMPLIANCE:
- XEP-0045 §7.10: Registering with a Room
- XEP-0077: In-Band Registration
- XEP-0004: Data Forms (for registration form)

UPSTREAM SUBMISSION:
This could be contributed to slixmpp as a feature enhancement.
"""

import logging
from typing import Dict, Any, Optional

log = logging.getLogger(__name__)


def apply_patch():
    """Add room membership request support to slixmpp XEP-0045."""
    try:
        from slixmpp.plugins.xep_0045.muc import XEP_0045
        from slixmpp.exceptions import IqError, IqTimeout
    except ImportError:
        log.warning("Could not import slixmpp XEP-0045 plugin, skipping membership patch")
        return

    async def request_room_membership(self, room: str, nickname: str, reason: str = "", *,
                                       mfrom: Optional[str] = None,
                                       timeout: int = 10) -> Dict[str, Any]:
        """
        Request membership in a members-only room.

        Uses XEP-0077 in-band registration to request membership. The room
        may auto-approve or queue the request for admin approval.

        :param room: Room JID to request membership from
        :param nickname: Desired nickname for the room
        :param reason: Optional reason/message for room admin
        :param mfrom: (for components) JID to send request from
        :param timeout: Timeout in seconds for IQ responses

        :returns: Dict with 'success' (bool) and 'error' (str or None)

        Example:
            result = await xep_0045.request_room_membership(
                'room@conference.example.com',
                nickname='mynick',
                reason='I would like to join this group'
            )
            if result['success']:
                print("Membership requested successfully")
            else:
                print(f"Failed: {result['error']}")
        """
        result = {'success': False, 'error': None}

        try:
            # Check if XEP-0077 plugin is loaded
            if 'xep_0077' not in self.xmpp.plugin:
                result['error'] = "XEP-0077 (In-Band Registration) plugin not loaded"
                log.error("XEP-0077 plugin required for room membership requests")
                return result

            # Step 1: Get registration form from room (IQ-get)
            # Use XEP-0077 plugin's get_registration method
            try:
                registration_form = await self.xmpp['xep_0077'].get_registration(
                    jid=room,
                    ifrom=mfrom,
                    timeout=timeout
                )
            except IqTimeout:
                result['error'] = "Timeout requesting registration form from room"
                log.warning(f"Timeout getting registration form from {room}")
                return result
            except IqError as e:
                error_condition = e.iq['error']['condition']
                error_text = e.iq['error'].get('text', '')
                result['error'] = f"Room rejected registration form request: {error_condition}"
                log.warning(f"Registration form request rejected by {room}: {error_condition} - {error_text}")
                return result

            # Step 2: Parse form to understand what fields are needed
            # Most rooms just ask for username/nickname, some may have additional fields
            reg_query = registration_form['register']

            # Step 3: Submit registration (IQ-set)
            # Create IQ manually and enable register stanza plugin
            iq_set = self.xmpp.Iq()
            iq_set['type'] = 'set'
            iq_set['to'] = room
            if mfrom:
                iq_set['from'] = mfrom
            iq_set.enable('register')
            reg_submit = iq_set['register']

            # Check if form uses data forms (XEP-0004) or simple fields
            if reg_query['form']['type']:
                # Data form present - use form submission
                form = reg_submit['form']
                form['type'] = 'submit'

                # Get list of field vars in the original form
                form_fields = {f['var']: f for f in reg_query['form']}

                log.debug(f"Registration form fields: {list(form_fields.keys())}")

                # Add FORM_TYPE if present in original
                if 'FORM_TYPE' in form_fields:
                    form.add_field(
                        var='FORM_TYPE',
                        ftype='hidden',
                        value=form_fields['FORM_TYPE'].get_value()
                    )

                # Add nickname field - check for standard MUC nickname field first
                nick_field = None
                for field_name in ['muc#register_roomnick', 'nick', 'nickname', 'username']:
                    if field_name in form_fields:
                        nick_field = field_name
                        break

                if nick_field:
                    form.add_field(var=nick_field, value=nickname)
                    log.debug(f"Added nickname field '{nick_field}' with value '{nickname}'")
                else:
                    log.warning(f"No nickname field found in registration form for {room}")
                    result['error'] = "Registration form has no nickname field"
                    return result

                # Add reason if provided AND if there's a suitable field in the form
                if reason:
                    reason_field = None
                    for field_name in ['muc#register_reason', 'reason', 'message', 'text', 'comments']:
                        if field_name in form_fields:
                            reason_field = field_name
                            break

                    if reason_field:
                        form.add_field(var=reason_field, value=reason)
                        log.debug(f"Added reason field '{reason_field}'")
                    else:
                        log.debug(f"No reason field in form, reason will not be sent")
            else:
                # Simple registration (no data form) - use direct fields
                reg_submit['username'] = nickname
                if reason:
                    # Try to add reason field (not standard but some servers support it)
                    reg_submit['misc'] = reason

            # Send registration
            try:
                await iq_set.send(timeout=timeout)
                result['success'] = True
                log.info(f"Successfully requested membership for {room}")
            except IqTimeout:
                result['error'] = "Timeout submitting membership request"
                log.warning(f"Timeout submitting membership request to {room}")
            except IqError as e:
                error_condition = e.iq['error']['condition']
                error_text = e.iq['error'].get('text', '')

                # Map common errors to user-friendly messages
                if error_condition == 'conflict':
                    result['error'] = f"Username '{nickname}' already registered"
                elif error_condition == 'not-acceptable':
                    result['error'] = "Registration form incomplete or invalid"
                elif error_condition == 'forbidden':
                    result['error'] = "You are banned from this room"
                elif error_condition == 'registration-required':
                    result['error'] = "Membership request already pending"
                else:
                    result['error'] = f"Registration rejected: {error_condition}"
                    if error_text:
                        result['error'] += f" - {error_text}"

                log.warning(f"Membership request rejected by {room}: {error_condition} - {error_text}")

        except Exception as e:
            result['error'] = f"Unexpected error: {str(e)}"
            log.error(f"Error requesting membership for {room}: {e}")
            import traceback
            log.error(traceback.format_exc())

        return result

    # Add the method to XEP_0045 class
    XEP_0045.request_room_membership = request_room_membership
    log.debug("Applied XEP-0045 membership request enhancement")
