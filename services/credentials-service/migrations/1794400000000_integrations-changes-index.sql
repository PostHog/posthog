-- Up Migration

-- Serves GET /v1/integrations/changes: rows in (updated_at, id) order after a keyset cursor.
-- Without it, each page sorts the whole table. The table is empty when this ships, so a plain
-- CREATE INDEX takes no meaningful lock. Run an index added later with CONCURRENTLY.
CREATE INDEX integrations_updated_at_id ON integrations (updated_at, id);

-- Down Migration

DROP INDEX integrations_updated_at_id;
