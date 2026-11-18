-- Rows in these tables are short-lived. Ingestion merges insert a claim and
-- delete it in the same transaction, and the sweeper GC deletes completed saga
-- ops once retention expires. The deletes leave empty pages at the end of the
-- heap, so vacuum keeps finding an empty tail and tries to truncate it.
-- Truncation needs an ACCESS EXCLUSIVE lock, which constant writes rarely leave
-- free, so each such autovacuum run polls for the lock for up to 5 s before it
-- gives up (Timeout:VacuumTruncate):
-- https://github.com/postgres/postgres/blob/REL_15_STABLE/src/backend/access/heap/vacuumlazy.c#L86-L88
-- Autovacuum vacuums each TOAST table as its own relation with its own
-- reloptions, so the toast. option is needed to turn truncation off there too:
-- https://www.postgresql.org/docs/15/sql-createtable.html#RELOPTION-VACUUM-TRUNCATE
--
-- SAFE: SET takes SHARE UPDATE EXCLUSIVE, which blocks no reads or writes. A
-- regular autovacuum cancels itself after deadlock_timeout; lock_timeout stops
-- the migration from waiting behind an anti-wraparound autovacuum, which does
-- not cancel, so the migration fails fast and can be re-run. Idempotent.

SET LOCAL lock_timeout = '2s';

ALTER TABLE lifecycle_op SET (vacuum_truncate = off, toast.vacuum_truncate = off);
ALTER TABLE lifecycle_op_person SET (vacuum_truncate = off, toast.vacuum_truncate = off);
