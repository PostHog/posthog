-- A lifecycle op row is updated once per saga step and each of its
-- per-person rows once per status change, all within the op's few hundred
-- milliseconds of life. Inserts pack a page before those updates arrive,
-- so most of them cannot be HOT and churn the indexes instead. Leaving
-- half of every new page free gives the row versions room on the page.
--
-- SAFE: SET (fillfactor) takes a SHARE UPDATE EXCLUSIVE lock, rewrites no
-- pages, and applies to pages written after it. Idempotent.

ALTER TABLE lifecycle_op SET (fillfactor = 50);
ALTER TABLE lifecycle_op_person SET (fillfactor = 50);
ALTER TABLE lifecycle_op_tmp SET (fillfactor = 50);
ALTER TABLE lifecycle_op_person_tmp SET (fillfactor = 50);
