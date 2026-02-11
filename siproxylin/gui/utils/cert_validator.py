"""
Client certificate validation utility for GUI.

Validates TLS client certificates without blocking on stdin password prompts.
Uses the same technique as drunk_xmpp/slixmpp_patches/cert_stdin_prevention.py
to prevent OpenSSL from prompting the terminal for encrypted key passwords.
"""

import ssl
from typing import Optional, Tuple


def validate_client_cert(cert_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate client certificate file without blocking on stdin.

    This function checks if a client certificate PEM file is valid and uses
    an UNENCRYPTED private key. It prevents OpenSSL from prompting stdin for
    passwords by passing password=b'' (empty bytes).

    Args:
        cert_path: Path to PEM file containing certificate and private key

    Returns:
        Tuple of (success: bool, error_message: Optional[str])
        - (True, None) if certificate is valid and key is unencrypted
        - (False, error_message) if there's any problem

    Note:
        The PEM file should contain both the certificate and unencrypted
        private key. Encrypted keys are not supported.
    """
    if not cert_path or not cert_path.strip():
        return (False, "No certificate path provided")

    try:
        # Create SSL context and try to load the certificate
        # IMPORTANT: password=b'' prevents OpenSSL from prompting stdin
        # If we pass password=None (default), OpenSSL will block waiting for terminal input
        ssl_context = ssl.create_default_context()
        ssl_context.load_cert_chain(cert_path, cert_path, password=b'')
        return (True, None)

    except ssl.SSLError as e:
        # SSLError usually means encrypted key or malformed certificate
        error_str = str(e).lower()
        if 'encrypted' in error_str or 'password' in error_str or 'bad decrypt' in error_str:
            return (False, "Private key is encrypted. Only unencrypted keys are supported. Please decrypt your private key first.")
        else:
            return (False, f"Invalid certificate or key: {e}")

    except FileNotFoundError:
        return (False, f"Certificate file not found: {cert_path}")

    except PermissionError:
        return (False, f"Permission denied reading certificate file: {cert_path}")

    except Exception as e:
        return (False, f"Failed to load certificate: {e}")
