--
-- posthog_batchimport table (keep in sync w/Django-managed copy in "posthog" local dev DB! Example:
-- `pg_dump -h localhost -p 5432 -U posthog -s -t posthog_batchimport posthog`
--

CREATE TABLE posthog_batchimport (
    id uuid PRIMARY KEY,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    lease_id text,
    leased_until timestamp with time zone,
    status text NOT NULL,
    status_message text,
    state jsonb,
    import_config jsonb NOT NULL,
    secrets text NOT NULL,
    team_id integer NOT NULL
);

CREATE INDEX posthog_batchimport_team_id_idx ON public.posthog_batchimport USING btree (team_id);

