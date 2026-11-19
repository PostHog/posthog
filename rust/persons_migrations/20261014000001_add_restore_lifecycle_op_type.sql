-- The person consistency repair claims lifecycle marks as op_type 'restore'.
--
-- SAFE: NOT VALID skips the table scan, so the swap holds ACCESS EXCLUSIVE only briefly;
-- lock_timeout bounds the wait, so the migration fails fast instead of queueing ingestion
-- merges behind it. The next migration validates in its own transaction. Idempotent.

SET LOCAL lock_timeout = '2s';

ALTER TABLE lifecycle_op DROP CONSTRAINT IF EXISTS lifecycle_op_op_type_check;
ALTER TABLE lifecycle_op ADD CONSTRAINT lifecycle_op_op_type_check
    CHECK (op_type IN ('merge', 'delete', 'restore')) NOT VALID;

ALTER TABLE lifecycle_op_tmp DROP CONSTRAINT IF EXISTS lifecycle_op_tmp_op_type_check;
ALTER TABLE lifecycle_op_tmp ADD CONSTRAINT lifecycle_op_tmp_op_type_check
    CHECK (op_type IN ('merge', 'delete', 'restore')) NOT VALID;
