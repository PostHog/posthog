-- Mirrors error_tracking/0042_errortrackingissuechange, which Django owns.
CREATE TABLE IF NOT EXISTS posthog_errortrackingissuechange (
    id uuid NOT NULL PRIMARY KEY,
    issue_id uuid NOT NULL,
    kind text NOT NULL,
    data jsonb DEFAULT '{}'::jsonb NOT NULL,
    snapshot jsonb DEFAULT '{}'::jsonb NOT NULL,
    operation_id uuid NOT NULL,
    bulk boolean DEFAULT false NOT NULL,
    actor_type text NOT NULL,
    actor_user_id integer NULL,
    actor_automation_id uuid NULL,
    causation_id uuid NULL,
    depth smallint DEFAULT 0 NOT NULL CHECK (depth >= 0),
    event_uuid uuid NULL,
    event_timestamp timestamp with time zone NULL,
    created_at timestamp with time zone DEFAULT (STATEMENT_TIMESTAMP()) NOT NULL,
    dispatched_at timestamp with time zone NULL,
    team_id integer NOT NULL,
    CONSTRAINT et_issue_change_actor_matches_type CHECK (
        (actor_automation_id IS NULL AND actor_type = 'ingestion' AND actor_user_id IS NULL)
        OR (actor_automation_id IS NULL AND actor_type = 'user' AND actor_user_id IS NOT NULL)
        OR (actor_automation_id IS NOT NULL AND actor_type = 'automation' AND actor_user_id IS NULL)
    )
);
