-- New mark_active boolean for HOT-friendly status transitions.
-- Old lifecycle_op_person_mark index kept until all callers migrate.
ALTER TABLE lifecycle_op_person
    ADD COLUMN IF NOT EXISTS mark_active BOOLEAN NOT NULL DEFAULT false;

UPDATE lifecycle_op_person
   SET mark_active = true
 WHERE status IN ('marked', 'sealed')
   AND mark_active = false;

-- Shadow table
ALTER TABLE lifecycle_op_person_tmp
    ADD COLUMN IF NOT EXISTS mark_active BOOLEAN NOT NULL DEFAULT false;

UPDATE lifecycle_op_person_tmp
   SET mark_active = true
 WHERE status IN ('marked', 'sealed')
   AND mark_active = false;
