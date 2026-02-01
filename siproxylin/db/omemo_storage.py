"""
OMEMO Storage implementation using SQLite database.
Implements the omemo.Storage interface for use with slixmpp-omemo.

This replaces JSON file storage with a proper database backend,
storing OMEMO cryptographic material in the omemo_storage table.
"""

import json
from pathlib import Path

from omemo.storage import Storage, Maybe, Just, Nothing
from omemo.types import JSONType


class OMEMOStorageDB(Storage):
    """
    OMEMO storage implementation using SQLite database backend.

    This replaces the JSON file storage with a proper database backend,
    allowing unified storage of OMEMO keys with other application data.

    Thread-safe: Uses the shared database connection from Database singleton.
    """

    def __init__(self, db, account_id: int) -> None:
        """
        Initialize OMEMO storage with SQLite backend.

        Args:
            db: Database instance (from get_db())
            account_id: Account ID to scope storage to
        """
        super().__init__()
        self.__db = db
        self.__account_id = account_id

    async def _load(self, key: str) -> Maybe[JSONType]:
        """
        Load a value from database.

        Args:
            key: The key identifying the value.

        Returns:
            The loaded value, if it exists.
        """
        row = self.__db.fetchone(
            "SELECT value FROM omemo_storage WHERE account_id = ? AND key = ?",
            (self.__account_id, key)
        )

        if row:
            value = json.loads(row['value'])
            return Just(value)

        return Nothing()

    async def _store(self, key: str, value: JSONType) -> None:
        """
        Store a value in database.

        Args:
            key: The key identifying the value.
            value: The value to store under the given key.
        """
        json_value = json.dumps(value)
        self.__db.execute(
            """
            INSERT INTO omemo_storage (account_id, key, value)
            VALUES (?, ?, ?)
            ON CONFLICT(account_id, key) DO UPDATE SET value = excluded.value
            """,
            (self.__account_id, key, json_value)
        )
        self.__db.commit()

    async def _delete(self, key: str) -> None:
        """
        Delete a value from database, if it exists.

        Args:
            key: The key identifying the value to delete.
        """
        self.__db.execute(
            "DELETE FROM omemo_storage WHERE account_id = ? AND key = ?",
            (self.__account_id, key)
        )
        self.__db.commit()
