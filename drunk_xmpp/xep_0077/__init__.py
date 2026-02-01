"""
Custom XEP-0077: In-Band Registration Implementation

This is a custom implementation that provides manual control over registration
IQ stanzas, allowing us to maintain a single connection and preserve CAPTCHA
challenges between form query and submission.

Unlike slixmpp's built-in XEP-0077 plugin, this implementation:
- Does NOT auto-trigger on connection
- Does NOT attempt authentication
- Provides explicit control over form query and submission timing
- Preserves the exact form state (including CAPTCHA) between operations
"""

from .registration import RegistrationClient

__all__ = ['RegistrationClient']
