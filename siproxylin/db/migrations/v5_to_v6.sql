-- Migration from schema version 5 to 6
-- Add occupant_id support for MUC reactions (Dino-compatible)

-- Step 1: Create new reaction table with occupant_id field
CREATE TABLE reaction_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    content_item_id INTEGER NOT NULL,
    jid_id INTEGER,                     -- For 1-1 reactions (nullable now)
    occupant_id INTEGER,                -- For MUC reactions (references occupant.id)
    time INTEGER NOT NULL,
    emojis TEXT,
    UNIQUE (account_id, content_item_id, jid_id) ON CONFLICT REPLACE,
    UNIQUE (account_id, content_item_id, occupant_id) ON CONFLICT REPLACE,
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE,
    FOREIGN KEY (content_item_id) REFERENCES content_item(id) ON DELETE CASCADE,
    FOREIGN KEY (jid_id) REFERENCES jid(id) ON DELETE CASCADE,
    FOREIGN KEY (occupant_id) REFERENCES occupant(id) ON DELETE CASCADE
);

-- Step 2: Copy existing data (all existing reactions are 1-1, so jid_id stays)
INSERT INTO reaction_new (id, account_id, content_item_id, jid_id, time, emojis)
SELECT id, account_id, content_item_id, jid_id, time, emojis
FROM reaction;

-- Step 3: Drop old table and rename
DROP TABLE reaction;
ALTER TABLE reaction_new RENAME TO reaction;

-- Step 4: Recreate index
CREATE INDEX reaction_content_item_idx ON reaction (content_item_id);

-- Update schema version
UPDATE _meta SET int_val = 6 WHERE name = 'schema_version';
