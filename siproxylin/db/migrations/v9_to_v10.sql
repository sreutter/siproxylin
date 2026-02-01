-- Migration v9 to v10: Rename ID columns to match XEP-0359 naming
--
-- Problem: DB column names didn't match XEP-0359 spec, causing confusion
-- - stanza_id stored msg.get('id') (basic message ID attribute)
-- - server_id stored msg['stanza_id']['id'] (XEP-0359 stanza-id element)
--
-- Solution: Rename to match XEP-0359 directly
-- - message_id stores msg.get('id') (basic message ID attribute)
-- - stanza_id stores msg['stanza_id']['id'] (XEP-0359 stanza-id element)
-- - origin_id stays the same (already correct)

-- Rename columns in message table
ALTER TABLE message RENAME COLUMN stanza_id TO message_id;
ALTER TABLE message RENAME COLUMN server_id TO stanza_id;

-- Rename columns in file_transfer table (for consistency)
ALTER TABLE file_transfer RENAME COLUMN stanza_id TO message_id;
ALTER TABLE file_transfer RENAME COLUMN server_id TO stanza_id;

-- Drop old indexes
DROP INDEX IF EXISTS message_stanza_id_idx;
DROP INDEX IF EXISTS message_server_id_idx;
DROP INDEX IF EXISTS file_transfer_stanza_id_idx;
DROP INDEX IF EXISTS file_transfer_server_id_idx;

-- Create new indexes with correct names
CREATE INDEX message_message_id_idx ON message (account_id, counterpart_id, message_id);
CREATE INDEX message_stanza_id_idx ON message (account_id, counterpart_id, stanza_id);

CREATE INDEX file_transfer_message_id_idx ON file_transfer (message_id) WHERE message_id IS NOT NULL;
CREATE INDEX file_transfer_stanza_id_idx ON file_transfer (stanza_id) WHERE stanza_id IS NOT NULL;
