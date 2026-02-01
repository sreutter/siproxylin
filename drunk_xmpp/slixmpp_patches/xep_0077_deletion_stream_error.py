"""
Fix for slixmpp XEP-0077 account deletion with immediate stream closure.

BUG DESCRIPTION:
When a user successfully deletes their account using cancel_registration(), per XEP-0077
the server should send an IQ result followed by a stream error and stream closure.
However, slixmpp's cancel_registration() only waits for the IQ response and doesn't
handle the stream closure, leading to a race condition where the stream closes before
the IQ callback can fire, causing IqTimeout.

PROTOCOL (XEP-0077 Section 3.2):
1. Client sends: <iq type='set'><query xmlns='jabber:iq:register'><remove/></query></iq>
2. Server responds: <iq type='result' id='...'/>
3. Server sends stream error: <stream:error><not-authorized/></stream:error>
4. Server closes stream

SERVER IMPLEMENTATIONS:
- XEP-0077 compliant: Send <not-authorized/> stream error (SHOULD per spec)
- conversations.im: Sends <conflict/> with text "User removed" (non-standard but functionally correct)

THE RACE CONDITION:
On fast servers (especially conversations.im), the IQ result and stream closure arrive
within milliseconds of each other. The stream closes before slixmpp's IQ response
handler can process the success callback, causing cancel_registration() to timeout
despite the deletion being successful.

TIMELINE EXAMPLE (conversations.im):
16:58:31.999 - SEND: <iq type="set"><query xmlns="jabber:iq:register"><remove /></query></iq>
16:58:32.635 - RECV: <iq type="result" id="..." />  ← SUCCESS (0.636s later)
16:58:32.636 - RECV: <stream:error><conflict /><text>User removed</text></stream:error>  ← 0.001s later!
16:58:32.636 - Stream closed
            ⮑ IQ callback never fires, cancel_registration() times out after 10s

FIX:
Provide a helper function that wraps cancel_registration() and adds a stream_error
event handler to detect successful deletion via stream closure. This allows proper
handling of both:
1. Normal IQ result (if stream stays open long enough)
2. Stream error indicating successful deletion (XEP-0077 compliant or conversations.im variant)

XMPP COMPLIANCE:
This fix implements the correct XEP-0077 behavior. The spec states:
"the server SHOULD then return a <not-authorized/> stream error and terminate all
active sessions for the entity"

SUBMITTED UPSTREAM:
[TODO: Create issue at https://codeberg.org/poezio/slixmpp/issues]
"""

import logging
import asyncio
from typing import Optional, Dict, Any
from slixmpp.exceptions import IqTimeout

log = logging.getLogger(__name__)


async def cancel_registration_with_stream_handling(
    client,
    jid: Optional[str] = None,
    ifrom: Optional[str] = None,
    timeout: float = 10.0
) -> Dict[str, Any]:
    """
    Cancel registration (delete account) with proper stream error handling.

    This works around slixmpp's cancel_registration() not handling the stream
    closure that occurs per XEP-0077 after successful account deletion.

    Args:
        client: slixmpp ClientXMPP instance with xep_0077 plugin loaded
        jid: Optional JID to send IQ to (usually None for own server)
        ifrom: Optional JID to send IQ from
        timeout: Timeout in seconds

    Returns:
        dict: {'success': bool, 'error': str or None}
    """
    result = {'success': False, 'error': None}
    deletion_done = asyncio.Event()

    async def on_stream_error(error_stanza):
        """
        Handle stream errors during deletion.

        Per XEP-0077, server SHOULD send <not-authorized/> stream error after deletion.
        Some servers (conversations.im) send <conflict/> instead.
        Both indicate successful deletion when server closes stream after deletion request.
        """
        try:
            # Get error condition
            error_condition = error_stanza.get('condition', '')
            error_text = error_stanza.get('text', '').lower()

            log.debug(f"Stream error during deletion: condition='{error_condition}', text='{error_text}'")

            # XEP-0077 compliant: <not-authorized/> after successful deletion
            if error_condition == 'not-authorized':
                log.info("✅ stream_error handler: Account deleted successfully (server sent <not-authorized/> per XEP-0077)")
                result['success'] = True
                deletion_done.set()
                log.debug(f"✅ stream_error handler: deletion_done.set() called, is_set={deletion_done.is_set()}")
                return

            # conversations.im non-standard: <conflict/> with "User removed"
            # This is technically incorrect per RFC 6120 (conflict is for multiple streams),
            # but it's functionally equivalent and indicates successful deletion
            if error_condition == 'conflict' and 'user removed' in error_text:
                log.info("✅ stream_error handler: Account deleted successfully (server sent <conflict/> with 'User removed')")
                result['success'] = True
                deletion_done.set()
                log.debug(f"✅ stream_error handler: deletion_done.set() called, is_set={deletion_done.is_set()}")
                return

            # Other stream errors - may indicate actual failure
            log.warning(f"Unexpected stream error during deletion: {error_condition} - {error_text}")

        except Exception as e:
            log.error(f"Error in stream_error handler: {e}")

    # Add stream_error handler
    client.add_event_handler('stream_error', on_stream_error)

    try:
        # Race between cancel_registration and stream_error event
        # Whoever completes first wins - this avoids waiting for IqTimeout when stream closes early
        log.debug(f"Starting deletion race: cancel_registration() vs stream_error handler...")

        # cancel_registration returns a Future, not a coroutine
        # We need to wrap it in a coroutine for asyncio.wait()
        async def cancel_wrapper():
            try:
                return await client['xep_0077'].cancel_registration(jid=jid, ifrom=ifrom, timeout=timeout)
            except IqTimeout:
                # This is expected when stream_error handler completes first
                # The IQ times out because the stream was closed after successful deletion
                log.debug("cancel_registration timed out (expected when stream closed early)")
                raise
            except Exception as e:
                log.debug(f"cancel_registration raised exception: {e}")
                raise

        # Create task for cancel_registration
        cancel_task = asyncio.create_task(cancel_wrapper())

        # Create task for waiting on deletion_done (set by stream_error handler)
        stream_error_task = asyncio.create_task(deletion_done.wait())

        # Wait for whichever completes first
        done, pending = await asyncio.wait(
            {cancel_task, stream_error_task},
            return_when=asyncio.FIRST_COMPLETED
        )

        # Check which task completed
        completed_task = done.pop()

        # Consume exceptions from pending tasks to avoid "Task exception was never retrieved"
        for task in pending:
            try:
                # Don't cancel - just suppress exceptions from the background task
                task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            except Exception:
                pass

        if completed_task == stream_error_task:
            # stream_error handler set deletion_done - this is the fast path
            log.info("✅ Deletion succeeded via stream_error handler (fast path - no IqTimeout wait)")
            # result['success'] already set by on_stream_error handler
        elif completed_task == cancel_task:
            # cancel_registration completed normally - IQ callback fired before stream closure
            try:
                await completed_task  # Get the result or re-raise exception
                log.info("✅ Deletion succeeded via IQ callback (slow path - stream stayed open)")
                result['success'] = True
            except IqTimeout:
                # This shouldn't happen since we raced against deletion_done.wait()
                # But if it does, check if stream_error set success
                if not result.get('success'):
                    log.error("❌ Account deletion timeout (IqTimeout and no stream error)")
                    result['error'] = "Timeout deleting account"
            except Exception as e:
                log.error(f"❌ cancel_registration raised exception: {e}")
                raise

    except Exception as e:
        log.error(f"Account deletion error: {e}")
        result['error'] = str(e)
        import traceback
        log.error(traceback.format_exc())
    finally:
        # Clean up event handler
        try:
            client.del_event_handler('stream_error', on_stream_error)
        except Exception as e:
            log.debug(f"Error removing stream_error handler (ignored): {e}")

    return result
