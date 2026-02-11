"""
Patch for slixmpp to prevent stdin password prompting for client certificates.

BUG DESCRIPTION:
When slixmpp's XMLStream.get_ssl_context() loads client certificates, if the
private key is encrypted, OpenSSL will prompt for password on stdin/terminal.
This is unacceptable for GUI applications.

IMPACT:
- GUI apps hang waiting for terminal input
- User has no idea what's happening
- Can't use encrypted keys at all

FIX:
Intercept certificate loading and pass a callback to prevent stdin prompting.
For encrypted keys, this causes an immediate SSLError with clear error message
instead of prompting.

NOTE: Currently only supports UNENCRYPTED keys. Users must decrypt their keys
before use. Future enhancement could add password field support.

XMPP COMPLIANCE:
This fix does not violate any XMPP spec. Client certificates are part of TLS,
which is transport-layer security. Both STARTTLS and direct TLS (xmpps) support
client certificate authentication via SASL EXTERNAL mechanism.
"""

import ssl
import logging
from typing import Optional

log = logging.getLogger(__name__)


def apply_patch():
    """
    Patch slixmpp's XMLStream to prevent stdin password prompting.

    Intercepts certificate loading to prevent OpenSSL from prompting terminal
    for passwords on encrypted keys.
    """
    from slixmpp.xmlstream import XMLStream

    # Store original method
    if hasattr(XMLStream, '_original_get_ssl_context'):
        log.debug("cert_password patch already applied, skipping")
        return

    XMLStream._original_get_ssl_context = XMLStream.get_ssl_context

    def get_ssl_context_no_stdin_prompt(self):
        """
        Get SSL context while preventing stdin password prompting.

        This wraps the original get_ssl_context() to prevent OpenSSL from
        prompting the terminal for passwords on encrypted keys.
        """
        # If we have cert/key configured, always handle it ourselves to prevent stdin prompting
        if hasattr(self, 'certfile') and hasattr(self, 'keyfile') and self.certfile and self.keyfile:
            # Call original WITHOUT cert/key to get basic SSL context
            # Temporarily clear certfile/keyfile so original doesn't try to load
            saved_certfile = self.certfile
            saved_keyfile = self.keyfile
            self.certfile = None
            self.keyfile = None

            try:
                ssl_context = self._original_get_ssl_context()
            finally:
                # Restore regardless of success/failure
                self.certfile = saved_certfile
                self.keyfile = saved_keyfile

            # Now load cert chain with empty password to prevent stdin prompting
            # NOTE: Certificate validation happens in GUI before passing to DrunkXMPP
            # This code path should only be reached for valid, unencrypted certs
            # IMPORTANT: Pass empty bytes to prevent OpenSSL from prompting stdin
            # When password=None (not passed), OpenSSL will prompt terminal (bad for GUI)
            # When password=b'' (empty bytes), OpenSSL won't prompt
            try:
                ssl_context.load_cert_chain(
                    self.certfile,
                    self.keyfile,
                    password=b''
                )
                log.debug('Loaded cert file %s and key file %s', self.certfile, self.keyfile)
            except ssl.SSLError as e:
                error_msg = (
                    f"Failed to load client certificate '{self.certfile}'. "
                    f"The certificate may be encrypted, corrupted, or invalid. "
                    f"Only unencrypted PEM certificates are supported. "
                    f"Error: {e}"
                )
                log.error(error_msg)
                self.event('connection_failed', error_msg)
                raise ssl.SSLError(error_msg) from e
            except Exception as e:
                error_msg = f"Failed to load client certificate '{self.certfile}': {e}"
                log.error(error_msg, exc_info=True)
                self.event('connection_failed', error_msg)
                raise RuntimeError(error_msg) from e
        else:
            # No cert configured - use original behavior
            ssl_context = self._original_get_ssl_context()

        return ssl_context

    # Replace method
    XMLStream.get_ssl_context = get_ssl_context_no_stdin_prompt

    log.debug("Applied cert stdin prevention patch to slixmpp.xmlstream.XMLStream")
