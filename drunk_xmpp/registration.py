"""
XEP-0077: In-Band Registration

Provides functions for querying registration forms and submitting account registrations.
Uses our custom raw-socket XEP-0077 implementation to avoid slixmpp's auto-SASL behavior.

Registration flow:
- Query connects, retrieves form, disconnects (preserves form in memory)
- Submit reconnects with fresh socket, sends registration, disconnects
- This approach preserves CAPTCHA challenge IDs and avoids slixmpp's double-query bug

Functions:
- create_registration_session(): Create session object (no persistent connection)
- query_registration_form(): Query form (connects, queries, disconnects)
- submit_registration(): Submit registration (reconnects, submits, disconnects)
- close_registration_session(): Clean up session object
- change_password(): Change password for existing account
- delete_account(): Delete/unregister account from server (WARNING: permanent!)
"""

import logging
import asyncio
import uuid
from typing import Optional, Dict, Any

from slixmpp import ClientXMPP
from slixmpp.exceptions import IqError, IqTimeout

from drunk_xmpp.xep_0077 import RegistrationClient
from drunk_xmpp.slixmpp_patches import cancel_registration_with_stream_handling

logger = logging.getLogger('drunk-xmpp.registration')


# Session registry for active registrations
_sessions: Dict[str, RegistrationClient] = {}


async def create_registration_session(server: str,
                                      proxy_settings: Optional[Dict[str, Any]] = None,
                                      timeout: float = 15.0) -> Dict[str, Any]:
    """
    Create a new registration session with persistent connection.

    Args:
        server: Server address (e.g., 'xmpp.earth')
        proxy_settings: Optional proxy configuration
        timeout: Connection timeout in seconds

    Returns:
        dict: {
            'success': bool,
            'session_id': str or None,
            'error': str or None
        }
    """
    session_id = str(uuid.uuid4())

    try:
        # Create custom registration client
        client = RegistrationClient(server, proxy_settings)

        # Connect (without authentication!)
        result = await client.connect(timeout=timeout)

        if result['success']:
            # Store in registry
            _sessions[session_id] = client
            return {
                'success': True,
                'session_id': session_id,
                'error': None
            }
        else:
            return {
                'success': False,
                'session_id': None,
                'error': result['error']
            }

    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        return {
            'success': False,
            'session_id': None,
            'error': str(e)
        }


async def query_registration_form(session_id: str, timeout: float = 15.0) -> Dict[str, Any]:
    """
    Query registration form using an active session.

    Args:
        session_id: Session ID from create_registration_session()
        timeout: Query timeout in seconds

    Returns:
        dict: {
            'success': bool,
            'fields': dict or None,
            'instructions': str or None,
            'captcha_data': dict or None,
            'error': str or None
        }
    """
    if session_id not in _sessions:
        return {
            'success': False,
            'fields': None,
            'instructions': None,
            'captcha_data': None,
            'error': f"Invalid session ID: {session_id}"
        }

    client = _sessions[session_id]
    return await client.query_form(timeout=timeout)


async def submit_registration(session_id: str, form_data: Dict[str, str],
                              timeout: float = 20.0) -> Dict[str, Any]:
    """
    Submit registration using an active session.

    Args:
        session_id: Session ID from create_registration_session()
        form_data: Form values (username, password, email, ocr, etc.)
        timeout: Submit timeout in seconds

    Returns:
        dict: {
            'success': bool,
            'jid': str or None,
            'error': str or None
        }
    """
    if session_id not in _sessions:
        return {
            'success': False,
            'jid': None,
            'error': f"Invalid session ID: {session_id}"
        }

    client = _sessions[session_id]
    return await client.submit_registration(form_data, timeout=timeout)


async def close_registration_session(session_id: str) -> None:
    """
    Close registration session and cleanup.

    Args:
        session_id: Session ID from create_registration_session()
    """
    if session_id in _sessions:
        client = _sessions[session_id]
        await client.disconnect()
        del _sessions[session_id]


async def change_password(jid: str, old_password: str, new_password: str,
                         proxy_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Change password for existing XMPP account.

    Args:
        jid: Full JID (username@server)
        old_password: Current password (for authentication)
        new_password: New password to set
        proxy_settings: Optional proxy configuration (same format as other functions)

    Returns:
        dict: {
            'success': bool,
            'error': str or None
        }
    """
    result = {
        'success': False,
        'error': None
    }

    client = None

    try:
        # Create client with current credentials
        client = ClientXMPP(jid, old_password)

        # CRITICAL: Set event loop for qasync integration
        # slixmpp requires explicit loop assignment to work with existing event loops
        client.loop = asyncio.get_event_loop()

        # Disable auto-connect
        client.use_aiodns = False

        # Register required plugins
        client.register_plugin('xep_0030')  # Service Discovery
        client.register_plugin('xep_0004')  # Data Forms
        client.register_plugin('xep_0077')  # In-Band Registration

        # Add XML stream event logging to debug IQ response handling
        def log_incoming_xml(xml_string):
            if 'jabber:iq:register' in xml_string or ('type="result"' in xml_string and 'iq' in xml_string):
                logger.info(f"[XML RECV] {xml_string}")

        def log_outgoing_xml(xml_string):
            if 'jabber:iq:register' in xml_string:
                logger.info(f"[XML SEND] {xml_string}")

        client.add_event_handler('xml_recv', log_incoming_xml)
        client.add_event_handler('xml_send', log_outgoing_xml)

        # Configure proxy if provided
        if proxy_settings:
            proxy_type = proxy_settings.get('proxy_type')
            proxy_host = proxy_settings.get('proxy_host')
            proxy_port = proxy_settings.get('proxy_port')
            proxy_username = proxy_settings.get('proxy_username')
            proxy_password = proxy_settings.get('proxy_password')

            if proxy_type and proxy_host and proxy_port:
                client.use_proxy = True
                client.proxy_config = {
                    'proxy_type': proxy_type.lower() if proxy_type else None,
                    'host': proxy_host,
                    'port': proxy_port,
                    'username': proxy_username,
                    'password': proxy_password
                }
                logger.info(f"Using proxy: {proxy_type} {proxy_host}:{proxy_port}")

        # Event to wait for password change completion
        password_changed = asyncio.Event()

        async def on_session_start(event):
            """Handle session start - change password."""
            try:
                logger.info(f"Changing password for {jid}...")

                # Use XEP-0077 to change password
                # This sends an IQ-set with the new password
                await client['xep_0077'].change_password(new_password, timeout=10)

                result['success'] = True
                logger.info(f"Password changed successfully for {jid}")

            except IqError as e:
                error_condition = e.iq['error']['condition']
                error_text = e.iq['error'].get('text', '')
                result['error'] = f"Server error: {error_condition} - {error_text}"
                logger.error(f"Password change failed: {error_condition}")

            except IqTimeout:
                result['error'] = "Timeout changing password"
                logger.error("Password change timeout")

            except Exception as e:
                result['error'] = f"Failed to change password: {e}"
                logger.error(f"Password change error: {e}")
                import traceback
                logger.error(traceback.format_exc())

            finally:
                password_changed.set()

        async def on_failed_auth(event):
            """Handle authentication failure."""
            result['error'] = "Authentication failed - check current password"
            logger.error("Auth failed during password change")
            password_changed.set()

        client.add_event_handler('session_start', on_session_start)
        client.add_event_handler('failed_auth', on_failed_auth)

        # Connect to server (slixmpp will do SRV resolution)
        logger.info(f"Connecting to change password for {jid}...")
        client.connect()

        # Wait for password change with timeout
        try:
            await asyncio.wait_for(password_changed.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            result['error'] = "Timeout during password change"
            logger.error(f"Timeout changing password for {jid}")

    except Exception as e:
        logger.error(f"Failed to change password: {e}")
        result['error'] = str(e)
        import traceback
        logger.error(traceback.format_exc())

    finally:
        # Cleanup
        if client:
            try:
                client.disconnect(wait=False)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(f"Cleanup error (ignored): {e}")

    return result


async def delete_account(jid: str, password: str,
                        proxy_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Delete/unregister XMPP account from server.

    WARNING: This permanently deletes the account and all associated data!
    This action cannot be undone.

    Args:
        jid: Full JID (username@server)
        password: Current password (for authentication)
        proxy_settings: Optional proxy configuration (same format as other functions)

    Returns:
        dict: {
            'success': bool,
            'error': str or None
        }
    """
    result = {
        'success': False,
        'error': None
    }

    client = None

    try:
        # Create client with current credentials
        client = ClientXMPP(jid, password)

        # CRITICAL: Set event loop IMMEDIATELY after creation, before ANYTHING else
        # slixmpp requires explicit loop assignment to work with existing event loops
        # Must be first thing after __init__ to avoid hybrid state
        client.loop = asyncio.get_event_loop()

        # Disable auto-connect
        client.use_aiodns = False

        # Register required plugins
        client.register_plugin('xep_0030')  # Service Discovery
        client.register_plugin('xep_0004')  # Data Forms
        client.register_plugin('xep_0077')  # In-Band Registration

        # Add XML stream event logging to debug IQ response handling
        def log_incoming_xml(xml_string):
            if 'jabber:iq:register' in xml_string or ('type="result"' in xml_string and 'iq' in xml_string):
                logger.info(f"[XML RECV] {xml_string}")

        def log_outgoing_xml(xml_string):
            if 'jabber:iq:register' in xml_string:
                logger.info(f"[XML SEND] {xml_string}")

        client.add_event_handler('xml_recv', log_incoming_xml)
        client.add_event_handler('xml_send', log_outgoing_xml)

        # Configure proxy if provided
        if proxy_settings:
            proxy_type = proxy_settings.get('proxy_type')
            proxy_host = proxy_settings.get('proxy_host')
            proxy_port = proxy_settings.get('proxy_port')
            proxy_username = proxy_settings.get('proxy_username')
            proxy_password = proxy_settings.get('proxy_password')

            if proxy_type and proxy_host and proxy_port:
                client.use_proxy = True
                client.proxy_config = {
                    'proxy_type': proxy_type.lower() if proxy_type else None,
                    'host': proxy_host,
                    'port': proxy_port,
                    'username': proxy_username,
                    'password': proxy_password
                }
                logger.info(f"Using proxy: {proxy_type} {proxy_host}:{proxy_port}")

        # Event to wait for deletion completion
        deletion_done = asyncio.Event()

        async def on_session_start(event):
            """Handle session start - delete account."""
            try:
                logger.info(f"Deleting account {jid}...")
                logger.warning("⚠ This will permanently delete the account and all data!")

                # Use patched cancel_registration with stream error handling
                # This handles the XEP-0077 compliant behavior where server closes
                # stream immediately after sending IQ result
                deletion_result = await cancel_registration_with_stream_handling(
                    client=client,
                    jid=None,
                    ifrom=None,
                    timeout=10.0
                )

                if deletion_result['success']:
                    result['success'] = True
                    logger.info(f"Account {jid} deleted successfully")
                else:
                    result['error'] = deletion_result.get('error', 'Unknown error')
                    logger.error(f"Account deletion failed: {result['error']}")

            except Exception as e:
                result['error'] = f"Failed to delete account: {e}"
                logger.error(f"Account deletion error: {e}")
                import traceback
                logger.error(traceback.format_exc())

            finally:
                deletion_done.set()

        async def on_failed_all_auth(event):
            """Handle authentication failure after all mechanisms exhausted."""
            result['error'] = "Authentication failed - check password"
            logger.error("All auth mechanisms failed during account deletion")
            deletion_done.set()

        client.add_event_handler('session_start', on_session_start)
        client.add_event_handler('failed_all_auth', on_failed_all_auth)

        # Connect to server (slixmpp will do SRV resolution)
        logger.info(f"Connecting to delete account {jid}...")
        client.connect()

        # Wait for deletion with timeout
        # Use wait_for with the event to allow other coroutines to run
        try:
            # Give slixmpp time to process the connection and response
            await asyncio.wait_for(deletion_done.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            result['error'] = "Timeout during account deletion"
            logger.error(f"Timeout deleting account {jid}")
            logger.error("Check if IQ response was received but handler didn't fire")

    except Exception as e:
        logger.error(f"Failed to delete account: {e}")
        result['error'] = str(e)
        import traceback
        logger.error(traceback.format_exc())

    finally:
        # Cleanup
        if client:
            try:
                client.disconnect(wait=False)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.debug(f"Cleanup error (ignored): {e}")

    return result
