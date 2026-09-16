-- no-transaction
--
-- Drop the old status-predicated uniqueness index now that all callers
-- use the mark_active boolean index instead. Removing this index enables
-- HOT updates on the status column.
DROP INDEX CONCURRENTLY IF EXISTS lifecycle_op_person_mark;
