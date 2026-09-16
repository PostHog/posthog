-- Statement text per fingerprint, joined by pgapi from ts_query_durations. Created
-- here rather than on first data so the join works before the log collector has
-- seen a statement.

CREATE TABLE IF NOT EXISTS cur_query_texts (
    server_id   text NOT NULL,
    instance    text NOT NULL DEFAULT 'writer',
    datname     text NOT NULL DEFAULT '',
    first_seen  timestamptz NOT NULL,
    last_seen   timestamptz NOT NULL,
    fingerprint bigint NOT NULL,
    query       text,
    PRIMARY KEY (server_id, instance, datname, fingerprint)
);
