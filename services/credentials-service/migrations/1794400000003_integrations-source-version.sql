-- Up Migration

-- The `row_version` of the Django row that the mirror route last wrote. The route refuses an
-- older version, so a late retry cannot overwrite a newer copy. Null on rows the mirror never wrote.
ALTER TABLE integrations ADD COLUMN source_version bigint;

-- The table is still empty when this ships, so a plain CREATE INDEX takes no meaningful lock.
CREATE INDEX integrations_kind_legacy_id ON integrations (kind, legacy_id) WHERE legacy_id IS NOT NULL;

-- Down Migration

DROP INDEX integrations_kind_legacy_id;
ALTER TABLE integrations DROP COLUMN source_version;
