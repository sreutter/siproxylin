-- Migration from schema v8 to v9
-- Replace text-based subscription field with clear boolean flags
-- Matches GUI checkbox semantics and is more efficient

-- Add new boolean columns for subscription state
ALTER TABLE roster ADD COLUMN we_see_their_presence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE roster ADD COLUMN they_see_our_presence INTEGER NOT NULL DEFAULT 0;
ALTER TABLE roster ADD COLUMN we_requested_subscription INTEGER NOT NULL DEFAULT 0;
ALTER TABLE roster ADD COLUMN they_requested_subscription INTEGER NOT NULL DEFAULT 0;

-- Migrate existing subscription data from text to boolean flags
-- 'none' -> [0,0]
-- 'to'   -> [1,0]  (we see theirs)
-- 'from' -> [0,1]  (they see ours)
-- 'both' -> [1,1]

UPDATE roster SET we_see_their_presence = 1 WHERE subscription IN ('to', 'both');
UPDATE roster SET they_see_our_presence = 1 WHERE subscription IN ('from', 'both');

-- Note: Keeping old 'subscription' column for now (backward compatibility during migration)
-- Will be removed in future version once all code is updated
