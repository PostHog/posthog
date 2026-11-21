-- These tables churn constantly. Saga steps update each op row several times,
-- ingestion merges insert and delete a claim in the same transaction, and the
-- sweeper GC deletes completed ops once retention expires. Vacuum regularly
-- finds empty pages at the end of the heap and tries to truncate them.
-- Truncation needs an ACCESS EXCLUSIVE lock, which constant writes rarely leave
-- free, so each such autovacuum run polls for the lock for up to 5 s before it
-- gives up (Timeout:VacuumTruncate):
-- https://github.com/postgres/postgres/blob/REL_15_STABLE/src/backend/access/heap/vacuumlazy.c#L86-L88
-- With truncation off, the heap stays at its high-water mark and inserts
-- reuse the freed pages through the free space map:
-- https://www.postgresql.org/docs/15/sql-createtable.html#RELOPTION-VACUUM-TRUNCATE
--
-- SAFE: SET takes SHARE UPDATE EXCLUSIVE, which blocks no reads or writes. A
-- regular autovacuum cancels itself after deadlock_timeout; lock_timeout stops
-- the migration from waiting behind an anti-wraparound autovacuum, which does
-- not cancel, so the migration fails fast and can be re-run. Idempotent.

SET LOCAL lock_timeout = '2s';

ALTER TABLE lifecycle_op SET (vacuum_truncate = off);
ALTER TABLE lifecycle_op_person SET (vacuum_truncate = off);
