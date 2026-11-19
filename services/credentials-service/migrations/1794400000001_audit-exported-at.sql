-- Up Migration

-- A column, not a watermark: audit rows commit out of order (a slow write transaction can commit
-- after a newer read batch), so a time watermark could skip a row for good.
ALTER TABLE audit_log ADD COLUMN exported_at timestamptz;

-- Holds only the backlog, so it stays small while the exporter keeps up.
CREATE INDEX audit_log_unexported ON audit_log (occurred_at) WHERE exported_at IS NULL;

-- The runtime role marks rows as exported. It may update this one column and nothing else, so it
-- still cannot rewrite or erase an audit row. Row locks (FOR UPDATE) need an UPDATE privilege on a column.
-- The role name comes from the same session setting as in the grants migration.
DO $$
DECLARE
    runtime_role text := nullif(current_setting('credentials_service.runtime_role', true), '');
BEGIN
    IF runtime_role IS NULL THEN
        RAISE NOTICE 'credentials_service.runtime_role is not set: skipping grants';
        RETURN;
    END IF;
    EXECUTE format('GRANT UPDATE (exported_at) ON audit_log TO %I', runtime_role);
END
$$;

-- Down Migration

DROP INDEX audit_log_unexported;
ALTER TABLE audit_log DROP COLUMN exported_at;
