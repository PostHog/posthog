-- no-transaction
--
-- Shadow-table counterpart: drop the old status-predicated index.
DROP INDEX CONCURRENTLY IF EXISTS lifecycle_op_person_tmp_mark;
