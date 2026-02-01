"""
OMEMO support classes for DrunkXMPP.

Contains:
- OMEMOStorage: JSON file-based OMEMO key storage
- XEP_0384Impl: OMEMO plugin implementation with BTBV support
- PluginCouldNotLoad: Exception for plugin initialization failures
"""

import logging
import json
from pathlib import Path
from typing import Dict, Optional, FrozenSet, Any
from slixmpp.plugins import register_plugin

# OMEMO imports
from omemo.storage import Storage, Maybe, Just, Nothing
from omemo.types import JSONType, DeviceInformation
from slixmpp_omemo import XEP_0384, TrustLevel


class OMEMOStorage(Storage):
    """
    OMEMO storage implementation using a JSON file backend.
    Based on the slixmpp-omemo example implementation.
    """

    def __init__(self, json_file_path: Path) -> None:
        super().__init__()
        self.__json_file_path = json_file_path
        self.__data: Dict[str, JSONType] = {}

        # Ensure parent directory exists
        self.__json_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing data
        try:
            with open(self.__json_file_path, encoding="utf8") as f:
                self.__data = json.load(f)
        except Exception:
            pass

    async def _load(self, key: str) -> Maybe[JSONType]:
        if key in self.__data:
            return Just(self.__data[key])
        return Nothing()

    async def _store(self, key: str, value: JSONType) -> None:
        self.__data[key] = value
        with open(self.__json_file_path, "w", encoding="utf8") as f:
            json.dump(self.__data, f, indent=2)

    async def _delete(self, key: str) -> None:
        self.__data.pop(key, None)
        with open(self.__json_file_path, "w", encoding="utf8") as f:
            json.dump(self.__data, f, indent=2)


class PluginCouldNotLoad(Exception):
    """Exception raised when OMEMO plugin fails to load."""
    pass


class XEP_0384Impl(XEP_0384):
    """
    OMEMO plugin implementation for DrunkXMPP.
    Supports both legacy OMEMO (0.3.0) and modern OMEMO (0.8.0+).
    """

    default_config = {
        "fallback_message": "This message is OMEMO encrypted.",
        "json_file_path": None,
        "storage_object": None
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.__storage: Storage

    def plugin_init(self) -> None:
        # Accept either a Storage object (for DB backend) or json_file_path (for file backend)
        if self.storage_object is not None:
            self.__storage = self.storage_object
        elif self.json_file_path:
            self.__storage = OMEMOStorage(Path(self.json_file_path))
        else:
            raise PluginCouldNotLoad("Either storage_object or json_file_path must be specified.")

        super().plugin_init()

    @property
    def storage(self) -> Storage:
        return self.__storage

    @property
    def _btbv_enabled(self) -> bool:
        """Enable Blind Trust Before Verification for automatic trust."""
        return True

    async def _devices_blindly_trusted(
        self,
        blindly_trusted: FrozenSet[DeviceInformation],
        identifier: Optional[str]
    ) -> None:
        """Called when devices are automatically trusted via BTBV."""
        log = logging.getLogger(__name__)
        log.info(f"[{identifier}] Devices trusted blindly: {blindly_trusted}")

    async def _prompt_manual_trust(
        self,
        manually_trusted: FrozenSet[DeviceInformation],
        identifier: Optional[str]
    ) -> None:
        """
        Called when manual trust decision is needed.
        Since BTBV is enabled, this should rarely be called.
        For now, we'll automatically trust all devices.
        """
        log = logging.getLogger(__name__)
        session_manager = await self.get_session_manager()

        for device in manually_trusted:
            log.info(f"[{identifier}] Auto-trusting device: {device}")
            await session_manager.set_trust(
                device.bare_jid,
                device.identity_key,
                TrustLevel.TRUSTED.value
            )


# Register our OMEMO plugin implementation
register_plugin(XEP_0384Impl)
