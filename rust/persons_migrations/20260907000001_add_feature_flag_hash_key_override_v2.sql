-- Experience-continuity hash key overrides, keyed by the stable integer feature_flag_id
-- instead of the flag's string key.
--
-- v1's unique index is (team_id, person_id, feature_flag_key), so it cannot serve a
-- (team_id, feature_flag_key) lookup: there is no access path for "every override
-- belonging to this flag", and per-flag lifecycle cleanup is therefore impossible.
-- Keying on the id gives cleanup that access path via the secondary index below, and
-- the id is stable across renames, so a rename needs no row work at all.
--
-- SAFE: creates a new, empty table. Nothing reads or writes it yet.

CREATE TABLE IF NOT EXISTS posthog_featureflaghashkeyoverride_v2 (
    team_id         INTEGER NOT NULL,
    person_id       BIGINT NOT NULL,
    feature_flag_id INTEGER NOT NULL,
    hash_key        VARCHAR(400) NOT NULL,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    CONSTRAINT posthog_featureflaghashkeyoverride_v2_pkey
        PRIMARY KEY (team_id, person_id, feature_flag_id)
);

-- No surrogate id column: the primary key already serves the read path, which looks up
-- by (team_id, person_id), and an identity column would only widen a table whose row
-- count is the problem.

-- Cleanup path: every override belonging to one flag, for hard-delete and for disabling
-- ensure_experience_continuity.
CREATE INDEX IF NOT EXISTS posthog_featureflaghashkeyoverride_v2_team_flag_idx
    ON posthog_featureflaghashkeyoverride_v2 (team_id, feature_flag_id);

-- No standalone person_id index: every person-scoped delete (merge, hard delete) already
-- predicates on team_id and person_id, which the primary key's leading columns serve.

-- No foreign keys: posthog_featureflag lives in the default database, and v1's reference
-- to posthog_person was dropped when that table was partitioned. Every lifecycle cleanup
-- here is application-initiated.
