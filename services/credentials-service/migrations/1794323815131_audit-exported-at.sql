-- Up Migration

-- A column, not a watermark: audit rows commit out of order (a slow write transaction can commit
-- after a newer read batch), so a time watermark could skip a row for good.
ALTER TABLE audit_log ADD COLUMN exported_at timestamptz;

-- Holds only the backlog, so it stays small while the exporter keeps up.
CREATE INDEX audit_log_unexported ON audit_log (occurred_at) WHERE exported_at IS NULL;

-- Down Migration

DROP INDEX audit_log_unexported;
ALTER TABLE audit_log DROP COLUMN exported_at;
