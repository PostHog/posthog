-- Validate the op_type constraints added NOT VALID by the previous migration.
--
-- SAFE: VALIDATE CONSTRAINT takes SHARE UPDATE EXCLUSIVE, which does not block inserts, updates or
-- deletes, so ingestion merges keep running during the scan. Idempotent.

ALTER TABLE lifecycle_op VALIDATE CONSTRAINT lifecycle_op_op_type_check;
ALTER TABLE lifecycle_op_tmp VALIDATE CONSTRAINT lifecycle_op_tmp_op_type_check;
