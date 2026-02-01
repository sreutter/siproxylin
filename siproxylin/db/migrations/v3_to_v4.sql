-- Migration from schema version 3 to 4
-- Add is_carbon field to track messages sent from other devices (XEP-0280)

-- Add is_carbon column to message table
-- 0 = regular message sent/received from THIS device
-- 1 = carbon copy (message sent from ANOTHER device)
ALTER TABLE message ADD COLUMN is_carbon INTEGER NOT NULL DEFAULT 0;

-- Add is_carbon column to file_transfer table
-- Same semantics as message table
ALTER TABLE file_transfer ADD COLUMN is_carbon INTEGER NOT NULL DEFAULT 0;

-- Update schema version
UPDATE _meta SET int_val = 4 WHERE name = 'schema_version';
