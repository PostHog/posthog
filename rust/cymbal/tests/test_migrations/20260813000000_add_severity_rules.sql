CREATE TABLE IF NOT EXISTS posthog_errortrackingseverityrule
(
    id uuid NOT NULL PRIMARY KEY,
    team_id integer NOT NULL,
    filters jsonb NOT NULL,
    bytecode jsonb NOT NULL,
    severity text NOT NULL,
    order_key integer NOT NULL,
    disabled_data jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);
