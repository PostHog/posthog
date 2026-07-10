-- Distinct-id claims: the call-time arbiter for person creation through
-- the personhog leader path.
--
-- A claim records "this (team_id, distinct_id) belongs to person_id"
-- BEFORE the person exists anywhere readable: a leader-path create is
-- acked once its changelog record is durable, but the person row and its
-- distinct-id mappings only reach Postgres after writer lag. During that
-- window an existence check cannot see the person, so a crashed creator's
-- restart (or a racing twin) would mint a duplicate. The primary key
-- makes claiming atomic and first-writer-wins: the loser learns the
-- winner's person_id at call time, adopts it, and idempotently re-issues
-- the create instead of allocating a new person.
--
-- Rows are transient bookkeeping. Once the writer applies the durable
-- posthog_persondistinctid mapping, the claim is redundant; the writer
-- reaps it in the same transaction that inserts the mapping. Correctness
-- never depends on reaping (or on any TTL) — a claim lives exactly as
-- long as the window it covers.
--
-- Deliberately no FK to posthog_person: the person's row does not exist
-- yet at claim time. That is the point of the table.
CREATE TABLE IF NOT EXISTS personhog_distinct_id_claims (
    team_id INTEGER NOT NULL,
    distinct_id VARCHAR(400) NOT NULL,
    person_id BIGINT NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, distinct_id)
);
