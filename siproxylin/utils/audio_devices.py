"""
Audio Device Detection and Management

Detects available audio input/output devices across platforms.
Provides hooks for GUI audio settings dialogs.
"""

import logging
import platform
import subprocess
from typing import List, Dict, Optional, Tuple


logger = logging.getLogger(__name__)


class AudioDevice:
    """Represents an audio device (microphone or speaker)."""

    def __init__(self, id: str, name: str, is_default: bool = False):
        """
        Args:
            id: Device identifier (used by av/MediaPlayer)
            name: Human-readable name
            is_default: Whether this is the system default device
        """
        self.id = id
        self.name = name
        self.is_default = is_default

    def __repr__(self):
        default_marker = " [DEFAULT]" if self.is_default else ""
        return f"AudioDevice(id={self.id!r}, name={self.name!r}{default_marker})"


class AudioDeviceManager:
    """
    Cross-platform audio device detection and management.

    Provides methods to:
    - Detect available input/output devices
    - Get system default devices
    - Store user preferences

    GUI hooks: Call get_input_devices() / get_output_devices() to populate
    audio settings dialog dropdowns.
    """

    def __init__(self):
        self.system = platform.system()
        self.logger = logging.getLogger(__name__)

    def get_input_devices(self) -> List[AudioDevice]:
        """
        Get list of available audio input devices (microphones).

        Returns:
            List of AudioDevice objects
        """
        if self.system == 'Linux':
            return self._get_linux_input_devices()
        elif self.system == 'Windows':
            return self._get_windows_input_devices()
        elif self.system == 'Darwin':  # macOS
            return self._get_macos_input_devices()
        else:
            self.logger.warning(f"Unsupported OS: {self.system}")
            return []

    def get_output_devices(self) -> List[AudioDevice]:
        """
        Get list of available audio output devices (speakers).

        Returns:
            List of AudioDevice objects
        """
        if self.system == 'Linux':
            return self._get_linux_output_devices()
        elif self.system == 'Windows':
            return self._get_windows_output_devices()
        elif self.system == 'Darwin':  # macOS
            return self._get_macos_output_devices()
        else:
            self.logger.warning(f"Unsupported OS: {self.system}")
            return []

    def get_default_input_device(self) -> Optional[AudioDevice]:
        """
        Get system default input device.

        Returns:
            AudioDevice or None if detection fails
        """
        devices = self.get_input_devices()
        for device in devices:
            if device.is_default:
                return device

        # Fallback: return first device
        if devices:
            return devices[0]

        return None

    def get_default_output_device(self) -> Optional[AudioDevice]:
        """
        Get system default output device.

        Returns:
            AudioDevice or None if detection fails
        """
        devices = self.get_output_devices()
        for device in devices:
            if device.is_default:
                return device

        # Fallback: return first device
        if devices:
            return devices[0]

        return None

    # =========================================================================
    # Linux (PipeWire/PulseAudio) Detection
    # =========================================================================

    def _get_linux_input_devices(self) -> List[AudioDevice]:
        """Get input devices on Linux via sounddevice (PortAudio)."""
        try:
            import sounddevice as sd

            devices = []
            default_input = sd.default.device[0]  # (input, output) tuple

            all_devices = sd.query_devices()
            for idx, device in enumerate(all_devices):
                if device['max_input_channels'] > 0:
                    # This is an input device
                    # Use index as ID (sounddevice uses indices)
                    device_id = str(idx)
                    device_name = device['name']
                    is_default = (idx == default_input)

                    devices.append(AudioDevice(device_id, device_name, is_default))

            self.logger.info(f"Found {len(devices)} input devices via sounddevice")
            return devices

        except ImportError:
            self.logger.warning("sounddevice not available - falling back to pactl")
            return self._get_linux_input_devices_pactl()
        except Exception as e:
            self.logger.error(f"Failed to detect Linux input devices: {e}")
            return []

    def _get_linux_input_devices_pactl(self) -> List[AudioDevice]:
        """Fallback: Get input devices on Linux via pactl (PulseAudio/PipeWire)."""
        devices = []

        try:
            # Get default source
            default_source = subprocess.check_output(
                ['pactl', 'get-default-source'],
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception as e:
            self.logger.warning(f"Failed to get default source: {e}")
            default_source = None

        try:
            # List all sources (microphones)
            output = subprocess.check_output(
                ['pactl', 'list', 'sources', 'short'],
                stderr=subprocess.DEVNULL
            ).decode()

            for line in output.strip().split('\n'):
                if not line:
                    continue

                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                device_id = parts[1]

                # Skip monitor devices (loopback from speakers)
                if '.monitor' in device_id:
                    continue

                # Get human-readable name
                try:
                    desc_output = subprocess.check_output(
                        ['pactl', 'list', 'sources'],
                        stderr=subprocess.DEVNULL
                    ).decode()

                    # Parse description from pactl output
                    device_name = self._parse_pulseaudio_name(desc_output, device_id)
                    if not device_name:
                        device_name = device_id  # Fallback to ID

                except Exception:
                    device_name = device_id

                is_default = (device_id == default_source)
                devices.append(AudioDevice(device_id, device_name, is_default))

            self.logger.info(f"Found {len(devices)} input devices on Linux (pactl)")
            return devices

        except FileNotFoundError:
            self.logger.warning("pactl not found - cannot detect audio devices")
            return []
        except Exception as e:
            self.logger.error(f"Failed to detect Linux input devices: {e}")
            return []

    def _get_linux_output_devices(self) -> List[AudioDevice]:
        """Get output devices on Linux via sounddevice (PortAudio) + pactl for default."""
        try:
            import sounddevice as sd

            devices = []

            # Get the REAL default from PulseAudio/PipeWire (more reliable than sounddevice)
            pactl_default = None
            try:
                pactl_default = subprocess.check_output(
                    ['pactl', 'get-default-sink'],
                    stderr=subprocess.DEVNULL
                ).decode('utf-8').strip()
                self.logger.debug(f"PulseAudio/PipeWire default sink: {pactl_default}")
            except:
                # Fall back to sounddevice default if pactl fails
                pactl_default = None

            # Query all sounddevice outputs
            all_devices = sd.query_devices()
            for idx, device in enumerate(all_devices):
                if device['max_output_channels'] > 0:
                    # This is an output device
                    device_id = str(idx)
                    device_name = device['name']

                    # Match pactl default to sounddevice device by name matching
                    is_default = False
                    if pactl_default:
                        # PulseAudio names like "alsa_output.pci-0000_05_00.6.analog-stereo"
                        # sounddevice names like "HD-Audio Generic: ALC1220 Analog (hw:2,0)"
                        # Try to match by checking if key parts are in the name
                        if 'analog' in pactl_default.lower() and 'analog' in device_name.lower():
                            is_default = True
                            self.logger.debug(f"Matched pactl default to sounddevice: {device_name}")
                        # More specific matching could be added here

                    # Fallback to sounddevice's default if no pactl match
                    if not is_default and idx == sd.default.device[1]:
                        is_default = True

                    devices.append(AudioDevice(device_id, device_name, is_default))

            self.logger.info(f"Found {len(devices)} output devices via sounddevice")
            return devices

        except ImportError:
            self.logger.warning("sounddevice not available - falling back to pactl")
            return self._get_linux_output_devices_pactl()
        except Exception as e:
            self.logger.error(f"Failed to detect Linux output devices: {e}")
            return []

    def _get_linux_output_devices_pactl(self) -> List[AudioDevice]:
        """Fallback: Get output devices on Linux via pactl (PulseAudio/PipeWire)."""
        devices = []

        try:
            # Get default sink
            default_sink = subprocess.check_output(
                ['pactl', 'get-default-sink'],
                stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception as e:
            self.logger.warning(f"Failed to get default sink: {e}")
            default_sink = None

        try:
            # List all sinks (speakers)
            output = subprocess.check_output(
                ['pactl', 'list', 'sinks', 'short'],
                stderr=subprocess.DEVNULL
            ).decode()

            for line in output.strip().split('\n'):
                if not line:
                    continue

                parts = line.split('\t')
                if len(parts) < 2:
                    continue

                device_id = parts[1]

                # Get human-readable name
                try:
                    desc_output = subprocess.check_output(
                        ['pactl', 'list', 'sinks'],
                        stderr=subprocess.DEVNULL
                    ).decode()

                    device_name = self._parse_pulseaudio_name(desc_output, device_id)
                    if not device_name:
                        device_name = device_id

                except Exception:
                    device_name = device_id

                is_default = (device_id == default_sink)
                devices.append(AudioDevice(device_id, device_name, is_default))

            self.logger.info(f"Found {len(devices)} output devices on Linux (pactl)")
            return devices

        except FileNotFoundError:
            self.logger.warning("pactl not found - cannot detect audio devices")
            return []
        except Exception as e:
            self.logger.error(f"Failed to detect Linux output devices: {e}")
            return []

    def _parse_pulseaudio_name(self, pactl_output: str, device_id: str) -> Optional[str]:
        """Parse human-readable name from pactl output."""
        lines = pactl_output.split('\n')
        found_device = False

        for line in lines:
            # Look for our device
            if f"Name: {device_id}" in line:
                found_device = True
                continue

            # Once found, look for description
            if found_device and 'Description:' in line:
                # Extract description
                desc = line.split('Description:', 1)[1].strip()
                return desc

            # Stop at next device
            if found_device and line.startswith('Source #') or line.startswith('Sink #'):
                break

        return None

    # =========================================================================
    # Windows (DirectShow) Detection
    # =========================================================================

    def _get_windows_input_devices(self) -> List[AudioDevice]:
        """Get input devices on Windows via ffmpeg -list_devices."""
        # TODO: Implement Windows device detection
        # Use: ffmpeg -list_devices true -f dshow -i dummy
        self.logger.warning("Windows audio device detection not yet implemented")

        # Fallback: return generic "Microphone" device
        return [AudioDevice('audio=Microphone', 'Default Microphone', is_default=True)]

    def _get_windows_output_devices(self) -> List[AudioDevice]:
        """Get output devices on Windows."""
        # TODO: Implement Windows device detection
        self.logger.warning("Windows audio device detection not yet implemented")

        # Fallback: return generic "Speakers" device
        return [AudioDevice('audio=Speakers', 'Default Speakers', is_default=True)]

    # =========================================================================
    # macOS (AVFoundation) Detection
    # =========================================================================

    def _get_macos_input_devices(self) -> List[AudioDevice]:
        """Get input devices on macOS via system_profiler."""
        # TODO: Implement macOS device detection
        # Use: system_profiler SPAudioDataType
        self.logger.warning("macOS audio device detection not yet implemented")

        # Fallback: return generic device
        return [AudioDevice(':0', 'Default Microphone', is_default=True)]

    def _get_macos_output_devices(self) -> List[AudioDevice]:
        """Get output devices on macOS."""
        # TODO: Implement macOS device detection
        self.logger.warning("macOS audio device detection not yet implemented")

        # Fallback: return generic device
        return [AudioDevice(':0', 'Default Speakers', is_default=True)]


# Global singleton
_audio_device_manager: Optional[AudioDeviceManager] = None


def get_audio_device_manager() -> AudioDeviceManager:
    """Get global AudioDeviceManager singleton."""
    global _audio_device_manager
    if _audio_device_manager is None:
        _audio_device_manager = AudioDeviceManager()
    return _audio_device_manager
