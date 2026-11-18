-- Persons tombstoned in Postgres whose ClickHouse tombstone is not yet confirmed.
--
-- SAFE: creates a new empty table and index only; takes no locks on existing tables. Idempotent.

CREATE TABLE IF NOT EXISTS person_tombstone_publish_queue (
    team_id         INTEGER NOT NULL,
    person_uuid     UUID NOT NULL,
    person_version  BIGINT NOT NULL,
    tombstoned_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMP WITH TIME ZONE,
    last_error      TEXT,
    given_up_at     TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (team_id, person_uuid)
);

CREATE INDEX IF NOT EXISTS person_tombstone_publish_queue_pending
    ON person_tombstone_publish_queue (tombstoned_at)
    WHERE given_up_at IS NULL;

COMMENT ON TABLE person_tombstone_publish_queue IS
    'Persons tombstoned by DeletePersons whose ClickHouse tombstone is not yet confirmed. Rows with given_up_at set are deleted in Postgres but may still be live in ClickHouse.';
