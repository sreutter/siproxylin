-- Migration from schema version 2 to 3
-- Add OMEMO key-value storage table for storing OMEMO crypto material

-- OMEMO key-value storage (replaces JSON files)
-- This table stores the internal OMEMO library data (identity keys, sessions, pre-keys, etc.)
-- The omemo_device table remains separate for GUI display metadata
CREATE TABLE omemo_storage (
    account_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,  -- JSON-serialized value
    PRIMARY KEY (account_id, key),
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE
);

CREATE INDEX omemo_storage_account_idx ON omemo_storage (account_id);

-- Update schema version
UPDATE _meta SET int_val = 3 WHERE name = 'schema_version';
