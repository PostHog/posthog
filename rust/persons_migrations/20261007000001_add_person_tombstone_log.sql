-- Shared log of person tombstone generations, written by the transaction that tombstones the person.
--
-- person_tombstone_publish_queue keeps one row per person and drops it on the first ack, so a second
-- reader never sees it. The distinct ids it reports come from rows that a revival changes and the
-- Postgres cleanup drain erases. This log keeps one row per deletion generation instead, with a copy
-- of the distinct ids and versions that generation tombstoned. Each consumer acks a generation on its
-- own, and the copy stays until every consumer has acked, however long one of them is down.
--
-- log_id identifies a generation, not (person_uuid, person_version): the drain can remove a person
-- and a later create can restart its versions. An ack names the exact log_id it processed, so a stale
-- ack can never complete a later generation of the same person.
--
-- No foreign key to posthog_person or posthog_persondistinctid: the drain and team teardown remove
-- those rows, and the copy must outlive them. The distinct id rows are not cascaded either: a
-- generation can hold many distinct ids, so retirement deletes them in bounded batches before the
-- generation itself.
--
-- SAFE: creates new empty tables and indexes only; takes no locks on existing tables. Idempotent.
-- The replica writes these tables only when TOMBSTONE_LOG_CAPTURE_ENABLED is set.

CREATE TABLE IF NOT EXISTS person_tombstone_log (
    log_id                BIGSERIAL PRIMARY KEY,
    team_id               INTEGER NOT NULL,
    person_uuid           UUID NOT NULL,
    person_version        BIGINT NOT NULL,
    tombstoned_at         TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    publication_acked_at  TIMESTAMP WITH TIME ZONE,
    membership_acked_at   TIMESTAMP WITH TIME ZONE,
    CONSTRAINT person_tombstone_log_team_scope UNIQUE (log_id, team_id)
);

CREATE INDEX IF NOT EXISTS person_tombstone_log_publication_pending
    ON person_tombstone_log (log_id)
    WHERE publication_acked_at IS NULL;

CREATE INDEX IF NOT EXISTS person_tombstone_log_membership_pending
    ON person_tombstone_log (log_id)
    WHERE membership_acked_at IS NULL;

CREATE INDEX IF NOT EXISTS person_tombstone_log_retirable
    ON person_tombstone_log (log_id)
    WHERE publication_acked_at IS NOT NULL AND membership_acked_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS person_tombstone_log_team
    ON person_tombstone_log (team_id, log_id);

CREATE INDEX IF NOT EXISTS person_tombstone_log_person
    ON person_tombstone_log (team_id, person_uuid, log_id);

CREATE TABLE IF NOT EXISTS person_tombstone_log_distinct_id (
    id           BIGSERIAL PRIMARY KEY,
    team_id      INTEGER NOT NULL,
    log_id       BIGINT NOT NULL,
    distinct_id  TEXT NOT NULL,
    version      BIGINT NOT NULL,
    -- A distinct id row always carries the team of its generation.
    CONSTRAINT person_tombstone_log_distinct_id_generation
        FOREIGN KEY (log_id, team_id) REFERENCES person_tombstone_log (log_id, team_id)
);

CREATE INDEX IF NOT EXISTS person_tombstone_log_distinct_id_page
    ON person_tombstone_log_distinct_id (team_id, log_id, id);

COMMENT ON TABLE person_tombstone_log IS
    'One row per person tombstone generation. Retired after both publication and membership ack it.';
COMMENT ON TABLE person_tombstone_log_distinct_id IS
    'The distinct ids and versions one tombstone generation wrote. Deleted in bounded batches when the generation retires.';
