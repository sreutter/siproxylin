"""
OMEMO Device Management module for DrunkXMPP.

Provides methods for querying OMEMO device information and trust levels.
"""

from typing import List, Dict, Any
import base64


class OMEMODevicesMixin:
    """
    Mixin providing OMEMO device management functionality.

    Requirements (provided by DrunkXMPP):
    - self.plugin: Dict of loaded slixmpp plugins
    - self.omemo_enabled: Boolean indicating if OMEMO is enabled
    - self.logger: Logger instance
    """

    # ============================================================================
    # OMEMO Device Management
    # ============================================================================

    async def get_omemo_devices(self, jid: str) -> List[Dict[str, Any]]:
        """
        Get OMEMO device information for a JID.

        Args:
            jid: Bare JID to get devices for

        Returns:
            List of device dicts with keys:
            - device_id: Device ID (int)
            - identity_key: Base64-encoded identity key (fingerprint)
            - trust_level: Trust level name (str): TRUSTED, BLINDLY_TRUSTED, UNDECIDED, DISTRUSTED
            - label: Device label (str, optional)
            - active: Whether device is active (bool)
        """
        if not self.omemo_enabled:
            self.logger.warning("OMEMO not enabled, cannot get devices")
            return []

        try:
            xep_0384 = self.plugin['xep_0384']
            session_manager = await xep_0384.get_session_manager()

            # Get device information from session manager
            device_infos = await session_manager.get_device_information(jid)

            devices = []
            for device_info in device_infos:
                # Convert bytes identity_key to base64 string
                identity_key_b64 = base64.b64encode(device_info.identity_key).decode('ascii')

                # Check if device is active (active is FrozenSet of (namespace, bool) tuples)
                is_active = any(active for namespace, active in device_info.active)

                devices.append({
                    'device_id': device_info.device_id,
                    'identity_key': identity_key_b64,
                    'trust_level': device_info.trust_level_name,
                    'label': device_info.label,
                    'active': is_active
                })

            self.logger.debug(f"Found {len(devices)} OMEMO devices for {jid}")
            return devices

        except Exception as e:
            self.logger.exception(f"Failed to get OMEMO devices for {jid}: {e}")
            return []

    async def get_own_omemo_devices(self) -> List[Dict[str, Any]]:
        """
        Get our own OMEMO devices.

        Returns:
            List of device dicts with keys:
            - device_id: Device ID (int)
            - identity_key: Base64-encoded identity key (fingerprint)
            - trust_level: Trust level name (str): TRUSTED, BLINDLY_TRUSTED, UNDECIDED, DISTRUSTED
            - label: Device label (str, optional)
            - active: Whether device is active (bool)
        """
        if not self.omemo_enabled:
            self.logger.warning("OMEMO not enabled, cannot get own devices")
            return []

        try:
            xep_0384 = self.plugin['xep_0384']
            session_manager = await xep_0384.get_session_manager()

            # Use get_own_device_information() which returns (this_device, other_own_devices)
            this_device, other_own_devices = await session_manager.get_own_device_information()

            devices = []

            # Add this device (the current one)
            identity_key_b64 = base64.b64encode(this_device.identity_key).decode('ascii')
            is_active = any(active for namespace, active in this_device.active)
            devices.append({
                'device_id': this_device.device_id,
                'identity_key': identity_key_b64,
                'trust_level': this_device.trust_level_name,
                'label': this_device.label,
                'active': is_active
            })

            # Add other own devices
            for device_info in other_own_devices:
                identity_key_b64 = base64.b64encode(device_info.identity_key).decode('ascii')
                is_active = any(active for namespace, active in device_info.active)
                devices.append({
                    'device_id': device_info.device_id,
                    'identity_key': identity_key_b64,
                    'trust_level': device_info.trust_level_name,
                    'label': device_info.label,
                    'active': is_active
                })

            self.logger.debug(f"Found {len(devices)} own OMEMO devices")
            return devices

        except Exception as e:
            self.logger.exception(f"Failed to get own OMEMO devices: {e}")
            return []

    async def set_omemo_trust(self, jid: str, device_id: int, trust_level_name: str) -> bool:
        """
        Set trust level for an OMEMO device.

        Args:
            jid: Bare JID owning the device
            device_id: Device ID to trust/distrust
            trust_level_name: Trust level string (TRUSTED, BLINDLY_TRUSTED, UNDECIDED, DISTRUSTED)

        Returns:
            True if successful, False otherwise
        """
        if not self.omemo_enabled:
            self.logger.warning("OMEMO not enabled, cannot set trust")
            return False

        try:
            xep_0384 = self.plugin['xep_0384']
            session_manager = await xep_0384.get_session_manager()

            # Get device information to retrieve identity key
            device_infos = await session_manager.get_device_information(jid)

            # Find the specific device
            for device_info in device_infos:
                if device_info.device_id == device_id:
                    # Set trust in library
                    await session_manager.set_trust(
                        jid,
                        device_info.identity_key,
                        trust_level_name
                    )
                    self.logger.info(f"Set trust for device {device_id} of {jid} to {trust_level_name}")
                    return True

            self.logger.error(f"Device {device_id} not found for {jid}")
            return False

        except Exception as e:
            self.logger.exception(f"Failed to set OMEMO trust: {e}")
            return False
