-- Migration v1 → v2: Add message retry tracking
-- Phase 4: Message Retry Logic (TODO-retry-logic.md)

-- Add retry tracking columns to message table
ALTER TABLE message ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE message ADD COLUMN first_retry_attempt INTEGER;  -- Timestamp of first retry
ALTER TABLE message ADD COLUMN last_retry_attempt INTEGER;   -- Timestamp of last retry

-- Update schema version
UPDATE _meta SET int_val = 2 WHERE name = 'schema_version';
