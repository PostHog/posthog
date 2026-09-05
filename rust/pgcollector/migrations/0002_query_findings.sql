-- Hourly roll-up of ts_query_stats, filled by the checks job so the 7-day regression
-- baseline reads 168 rows per query instead of rescanning the raw minute data.
CREATE TABLE IF NOT EXISTS ts_query_stats_1h (
    server_id          text NOT NULL,
    datname            text NOT NULL,
    queryid            bigint NOT NULL,
    hour               timestamptz NOT NULL,
    calls              bigint NOT NULL,
    total_ms           double precision NOT NULL,
    sumsq              double precision NOT NULL,
    rows               bigint NOT NULL,
    shared_blks_read   bigint NOT NULL,
    temp_blks_written  bigint NOT NULL,
    wal_bytes          bigint NOT NULL,
    instances          int NOT NULL,
    PRIMARY KEY (server_id, datname, queryid, hour)
);
CREATE INDEX IF NOT EXISTS ts_query_stats_1h_server_hour ON ts_query_stats_1h (server_id, hour);

CREATE TABLE IF NOT EXISTS ts_server_stats_1h (
    server_id  text NOT NULL,
    hour       timestamptz NOT NULL,
    total_ms   double precision NOT NULL,
    calls      bigint NOT NULL,
    PRIMARY KEY (server_id, hour)
);

CREATE TABLE IF NOT EXISTS query_findings (
    id             bigserial PRIMARY KEY,
    server_id      text NOT NULL,
    datname        text NOT NULL,
    fingerprint    bigint NOT NULL,
    queryid        bigint NOT NULL,
    rule           text NOT NULL,           -- new_heavy | new_heavy_burst | regression
    severity       text NOT NULL,           -- warning | critical
    status         text NOT NULL,           -- pending | open | resolved
    team           text NOT NULL,
    rotation       text NOT NULL,
    slack_channel  text,
    method         text NOT NULL,           -- database | comment | table | unowned
    attribution    jsonb NOT NULL,
    stats          jsonb NOT NULL,
    seen_count     int NOT NULL DEFAULT 0,
    miss_count     int NOT NULL DEFAULT 0,
    first_detected timestamptz NOT NULL,
    last_detected  timestamptz NOT NULL,
    resolved_at    timestamptz,
    UNIQUE (server_id, datname, fingerprint, rule)
);
CREATE INDEX IF NOT EXISTS query_findings_status ON query_findings (status, last_detected DESC);

CREATE TABLE IF NOT EXISTS checks_state (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL
);
