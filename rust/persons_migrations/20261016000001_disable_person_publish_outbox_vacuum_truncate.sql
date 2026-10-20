-- The outbox is a queue: identity appends rows and the publisher deletes them
-- moments later, so every vacuum finds an empty heap tail and tries to
-- truncate it. Truncation needs an ACCESS EXCLUSIVE lock, which a table under
-- constant inserts rarely grants, so each autovacuum run polls for the lock
-- for up to 5 s before it gives up (Timeout:VacuumTruncate):
-- https://github.com/postgres/postgres/blob/REL_15_STABLE/src/backend/access/heap/vacuumlazy.c#L86-L88
-- With truncation off, inserts reuse the freed pages through the free space
-- map and the heap stays at its high-water mark:
-- https://www.postgresql.org/docs/15/sql-createtable.html#RELOPTION-VACUUM-TRUNCATE
ALTER TABLE person_publish_outbox SET (vacuum_truncate = off);
ALTER TABLE person_publish_outbox_tmp SET (vacuum_truncate = off);
