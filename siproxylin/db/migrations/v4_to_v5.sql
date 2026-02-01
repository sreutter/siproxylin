-- Migration from schema version 4 to 5
-- Add MUC OMEMO compatibility tracking (XEP-0384 requirements)

-- Add MUC feature flags to conversation table
-- XEP-0384 requires: MUST be muc_nonanonymous, SHOULD be muc_membersonly
ALTER TABLE conversation ADD COLUMN muc_nonanonymous INTEGER DEFAULT 0;
ALTER TABLE conversation ADD COLUMN muc_membersonly INTEGER DEFAULT 0;

-- Update schema version
UPDATE _meta SET int_val = 5 WHERE name = 'schema_version';
