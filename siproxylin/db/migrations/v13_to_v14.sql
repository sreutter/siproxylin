-- Migration v13 to v14: Drop obsolete MUC feature cache columns
--
-- Remove muc_nonanonymous and muc_membersonly from conversation table.
-- These were added in v4→v5 to cache MUC OMEMO compatibility, but are now obsolete:
--   - Data is now read from in-memory disco_cache (always fresh)
--   - Database cache became stale and caused bugs (encryption button showing incorrect state)
--   - Removed all code that reads/writes these columns
--
-- This migration removes the obsolete columns to clean up the schema.
-- No data migration needed - disco_cache is populated on room join.

-- Drop obsolete MUC feature columns
ALTER TABLE conversation DROP COLUMN muc_nonanonymous;
ALTER TABLE conversation DROP COLUMN muc_membersonly;

-- Update schema version
UPDATE _meta SET int_val = 14 WHERE name = 'schema_version';
