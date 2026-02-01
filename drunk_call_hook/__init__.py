"""
DrunkCallHook - Python bridge to DrunkCallService (Go)

Handles:
- Go process lifecycle (GoCallService - app-level, owned by MainWindow)
- gRPC communication with Go service (CallBridge - per-account)
- Error handling and reconnection

Architecture:
    MainWindow → GoCallService (single Go process)
                      ↓
    AccountManager → CallBridge (gRPC client, one per account)
"""

from .bridge import GoCallService, CallBridge

__version__ = "0.1.0"
__all__ = ["GoCallService", "CallBridge"]
