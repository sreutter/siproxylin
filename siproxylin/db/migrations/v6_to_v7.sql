-- Migration v6 to v7: Add message IDs to file_transfer table for deduplication
-- Date: 2025-12-19
-- Purpose: Fix MUC file duplicate issue - files sent from THIS device appear twice
--          because reflections can't be deduplicated without IDs

-- Add ID fields to file_transfer table (same as message table)
ALTER TABLE file_transfer ADD COLUMN stanza_id TEXT;
ALTER TABLE file_transfer ADD COLUMN origin_id TEXT;
ALTER TABLE file_transfer ADD COLUMN server_id TEXT;

-- Create indexes for efficient duplicate checking
CREATE INDEX IF NOT EXISTS file_transfer_stanza_id_idx ON file_transfer (stanza_id) WHERE stanza_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS file_transfer_origin_id_idx ON file_transfer (origin_id) WHERE origin_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS file_transfer_server_id_idx ON file_transfer (server_id) WHERE server_id IS NOT NULL;
