"""
Logging setup for DRUNK-XMPP-GUI.

Multi-account logging with separate log files per account.
Main application log + per-account app logs + per-account XML logs.
"""

import logging
import sys
from pathlib import Path
from typing import Optional
from logging.handlers import RotatingFileHandler

from .paths import get_paths


# Log format
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

# Maximum log file size before rotation (10 MB)
MAX_LOG_SIZE = 10 * 1024 * 1024

# Number of backup files to keep
BACKUP_COUNT = 5


def setup_main_logger(log_level: str = 'INFO') -> logging.Logger:
    """
    Setup the main application logger (global, not account-specific).

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)

    Returns:
        Main logger instance
    """
    paths = get_paths()

    # Create main logger
    logger = logging.getLogger('siproxylin')
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()  # Clear existing handlers

    # Console handler (always enabled for development)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # File handler (rotating)
    main_log_path = paths.main_log_path()
    file_handler = RotatingFileHandler(
        main_log_path,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.info(f"Main logger initialized (level: {log_level}, log: {main_log_path})")

    # Configure drunk-xmpp library logger (registration, xep_0077, etc.)
    # These write to main.log with facility name drunk-xmpp.*
    drunk_logger = logging.getLogger('drunk-xmpp')
    drunk_logger.setLevel(getattr(logging, log_level.upper()))
    drunk_logger.handlers.clear()
    drunk_logger.propagate = False

    # Console handler
    drunk_console = logging.StreamHandler(sys.stdout)
    drunk_console.setLevel(getattr(logging, log_level.upper()))
    drunk_console.setFormatter(console_formatter)
    drunk_logger.addHandler(drunk_console)

    # File handler (same file as main logger)
    drunk_file = RotatingFileHandler(
        main_log_path,
        maxBytes=MAX_LOG_SIZE,
        backupCount=BACKUP_COUNT,
        encoding='utf-8'
    )
    drunk_file.setLevel(getattr(logging, log_level.upper()))
    drunk_file.setFormatter(file_formatter)
    drunk_logger.addHandler(drunk_file)

    logger.info("DrunkXMPP library logger configured (facility: drunk-xmpp.*)")

    # Configure global exception hook to log uncaught exceptions
    def exception_hook(exc_type, exc_value, exc_traceback):
        """Log uncaught exceptions to file instead of just stderr."""
        if issubclass(exc_type, KeyboardInterrupt):
            # Don't log KeyboardInterrupt (Ctrl+C)
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        logger.critical("Uncaught exception:", exc_info=(exc_type, exc_value, exc_traceback))

    sys.excepthook = exception_hook
    logger.info("Global exception hook configured (uncaught exceptions → main.log)")

    return logger


def setup_account_logger(
    account_id: int,
    log_level: str = 'INFO',
    app_log_enabled: bool = True
) -> Optional[logging.Logger]:
    """
    Setup logging for a specific XMPP account.

    Creates application logger for per-account user actions.
    Note: XML logging is global (see main.py), not per-account.

    Args:
        account_id: Account ID from database
        log_level: Logging level
        app_log_enabled: Enable application logging

    Returns:
        Application logger instance (or None if disabled)
    """
    paths = get_paths()

    # Application logger
    if app_log_enabled:
        app_logger = logging.getLogger(f'siproxylin.account-{account_id}')
        app_logger.setLevel(getattr(logging, log_level.upper()))
        app_logger.handlers.clear()
        app_logger.propagate = False  # Don't propagate to root logger

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_formatter = logging.Formatter(
            f'[Account {account_id}] {LOG_FORMAT}',
            LOG_DATE_FORMAT
        )
        console_handler.setFormatter(console_formatter)
        app_logger.addHandler(console_handler)

        # File handler
        app_log_path = paths.account_app_log_path(account_id)
        file_handler = RotatingFileHandler(
            app_log_path,
            maxBytes=MAX_LOG_SIZE,
            backupCount=BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
        file_handler.setFormatter(file_formatter)
        app_logger.addHandler(file_handler)

        app_logger.info(f"Account {account_id} app logger initialized (level: {log_level})")
        return app_logger

    return None


def get_account_logger(account_id: int) -> logging.Logger:
    """
    Get existing logger for an account.

    Args:
        account_id: Account ID

    Returns:
        Logger instance
    """
    return logging.getLogger(f'siproxylin.account-{account_id}')




def set_log_level(logger_name: str, level: str):
    """
    Change log level for a specific logger.

    Args:
        logger_name: Logger name (e.g., 'drunk-xmpp.account-1')
        level: New log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper()))
    for handler in logger.handlers:
        handler.setLevel(getattr(logging, level.upper()))
    logger.info(f"Log level changed to {level.upper()}")


def cleanup_old_logs(retention_days: int):
    """
    Clean up old log files based on retention policy.

    Args:
        retention_days: Number of days to retain logs (0 = keep forever)
    """
    if retention_days <= 0:
        return

    import time
    from datetime import datetime, timedelta

    paths = get_paths()
    log_dir = paths.log_dir

    cutoff_time = time.time() - (retention_days * 86400)

    deleted_count = 0
    for log_file in log_dir.glob('*.log*'):
        if log_file.stat().st_mtime < cutoff_time:
            try:
                log_file.unlink()
                deleted_count += 1
            except Exception as e:
                print(f"Failed to delete old log {log_file}: {e}")

    if deleted_count > 0:
        logger = logging.getLogger('siproxylin')
        logger.info(f"Cleaned up {deleted_count} old log files (retention: {retention_days} days)")
