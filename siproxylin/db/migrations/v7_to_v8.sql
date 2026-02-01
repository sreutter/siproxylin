-- Migration from schema v7 to v8
-- Add error_text column to message table for storing error details

-- Add error_text column to message table
ALTER TABLE message ADD COLUMN error_text TEXT;

-- Create index for efficient error queries
CREATE INDEX IF NOT EXISTS message_error_idx ON message (account_id, marked) WHERE marked = 8;
