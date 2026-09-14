-- no-transaction
--
-- Drops the original mark index, superseded by the covering variant created
-- in the prior migration. Both indexes enforce the same mark constraint on
-- the same hot insert path, so keeping the pair would make every mark insert
-- maintain and arbitrate two identical unique indexes.
DROP INDEX CONCURRENTLY IF EXISTS lifecycle_op_person_mark;
