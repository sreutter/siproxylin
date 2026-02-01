"""
Path management for Siproxylin.

Three path modes:
- dev: Use local paths (./sip_dev_paths/*) - default for development
- xdg: Use XDG paths (~/.config, ~/.local/share, ~/.cache) - XDG standard
- dot: Use dot directory (~/.siproxylin/*) - simple, supports gocryptfs

Toggle via PATH_MODE constant or SIPROXYLIN_PATH_MODE environment variable.
"""

import os
from pathlib import Path
from typing import Optional


# Path mode: 'dev', 'xdg', or 'dot'
PATH_MODE = os.getenv('SIPROXYLIN_PATH_MODE', 'dev').lower()


class Paths:
    """
    Centralized path management for the application.
    """

    def __init__(self, profile: str = 'default'):
        """
        Initialize paths for the application.

        Args:
            profile: Profile name for multi-profile support (e.g., 'default', 'work', 'personal')
        """
        self.profile = profile
        self._project_root = Path(__file__).parent.parent.parent

    @property
    def project_root(self) -> Path:
        """Project root directory (where drunk-xmpp.py lives)."""
        return self._project_root

    @property
    def config_dir(self) -> Path:
        """Configuration directory."""
        if PATH_MODE == 'xdg':
            # XDG: ~/.config/siproxylin/<profile>/
            xdg_config = Path.home() / '.config'
            xdg_config.mkdir(mode=0o700, exist_ok=True)
            base = xdg_config / 'siproxylin'
        elif PATH_MODE == 'dot':
            # Dot: ~/.siproxylin/config/<profile>/
            dot_root = Path.home() / '.siproxylin'
            dot_root.mkdir(mode=0o700, exist_ok=True)
            base = dot_root / 'config'
        else:  # dev
            # Development: ./sip_dev_paths/config/
            base = self._project_root / 'sip_dev_paths' / 'config'

        path = base / self.profile if self.profile != 'default' else base
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def data_dir(self) -> Path:
        """Data directory (database, OMEMO keys, etc.)."""
        if PATH_MODE == 'xdg':
            # XDG: ~/.local/share/siproxylin/<profile>/
            xdg_data = Path.home() / '.local' / 'share'
            xdg_data.mkdir(parents=True, mode=0o700, exist_ok=True)
            base = xdg_data / 'siproxylin'
        elif PATH_MODE == 'dot':
            # Dot: ~/.siproxylin/data/<profile>/
            dot_root = Path.home() / '.siproxylin'
            dot_root.mkdir(mode=0o700, exist_ok=True)
            base = dot_root / 'data'
        else:  # dev
            # Development: ./sip_dev_paths/data/
            base = self._project_root / 'sip_dev_paths' / 'data'

        path = base / self.profile if self.profile != 'default' else base
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def cache_dir(self) -> Path:
        """Cache directory (avatars, thumbnails, etc.)."""
        if PATH_MODE == 'xdg':
            # XDG: ~/.cache/siproxylin/<profile>/
            xdg_cache = Path.home() / '.cache'
            xdg_cache.mkdir(mode=0o700, exist_ok=True)
            base = xdg_cache / 'siproxylin'
        elif PATH_MODE == 'dot':
            # Dot: ~/.siproxylin/cache/<profile>/
            dot_root = Path.home() / '.siproxylin'
            dot_root.mkdir(mode=0o700, exist_ok=True)
            base = dot_root / 'cache'
        else:  # dev
            # Development: ./sip_dev_paths/cache/
            base = self._project_root / 'sip_dev_paths' / 'cache'

        path = base / self.profile if self.profile != 'default' else base
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    @property
    def log_dir(self) -> Path:
        """Log directory."""
        if PATH_MODE == 'xdg':
            # XDG: ~/.local/share/siproxylin/<profile>/logs/
            base = self.data_dir / 'logs'
        elif PATH_MODE == 'dot':
            # Dot: ~/.siproxylin/logs/<profile>/
            # Ensure ~/.siproxylin root has secure permissions
            dot_root = Path.home() / '.siproxylin'
            dot_root.mkdir(mode=0o700, exist_ok=True)
            base = dot_root / 'logs'
            if self.profile != 'default':
                base = base / self.profile
        else:  # dev
            # Development: ./sip_dev_paths/logs/
            base = self._project_root / 'sip_dev_paths' / 'logs'

        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        return base

    @property
    def database_path(self) -> Path:
        """Main database file path."""
        db_path = self.data_dir / 'siproxylin.db'
        # Ensure secure permissions (0600)
        if db_path.exists():
            os.chmod(db_path, 0o600)
        return db_path

    def omemo_storage_path(self, account_id: int) -> Path:
        """
        OMEMO key storage path for a specific account.

        Args:
            account_id: Account ID from database

        Returns:
            Path to OMEMO JSON storage file
        """
        omemo_dir = self.data_dir / 'omemo'
        omemo_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        omemo_file = omemo_dir / f'account-{account_id}-keys.json'
        # Ensure secure permissions (0600)
        if omemo_file.exists():
            os.chmod(omemo_file, 0o600)
        return omemo_file

    def account_app_log_path(self, account_id: int) -> Path:
        """
        Application log path for a specific account.

        Args:
            account_id: Account ID from database

        Returns:
            Path to application log file
        """
        return self.log_dir / f'account-{account_id}-app.log'

    def account_xml_log_path(self, account_id: int) -> Path:
        """
        XML protocol log path for a specific account.

        Args:
            account_id: Account ID from database

        Returns:
            Path to XML log file
        """
        return self.log_dir / f'account-{account_id}-xml.log'

    def main_log_path(self) -> Path:
        """Main application log path (global, not account-specific)."""
        return self.log_dir / 'main.log'

    def avatar_cache_path(self, jid: str) -> Path:
        """
        Avatar cache path for a JID.

        Args:
            jid: Bare JID

        Returns:
            Path to avatar image file
        """
        avatars_dir = self.cache_dir / 'avatars'
        avatars_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize JID for filename
        safe_jid = jid.replace('/', '_').replace('@', '_at_')
        return avatars_dir / f'{safe_jid}.png'

    def attachment_storage_path(self, account_id: int, filename: str) -> Path:
        """
        Storage path for downloaded attachments.

        Args:
            account_id: Account ID
            filename: Original filename

        Returns:
            Path to store the attachment
        """
        attachments_dir = self.data_dir / 'attachments' / f'account-{account_id}'
        attachments_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

        # Ensure file gets secure permissions
        file_path = attachments_dir / filename
        return file_path


# Global instance for default profile
_default_paths: Optional[Paths] = None


def get_paths(profile: str = 'default') -> Paths:
    """
    Get Paths instance for a profile.

    Args:
        profile: Profile name (default: 'default')

    Returns:
        Paths instance
    """
    global _default_paths

    if profile == 'default':
        if _default_paths is None:
            _default_paths = Paths(profile)
        return _default_paths

    return Paths(profile)
