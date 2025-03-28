--
-- posthog_person table (keep in sync w/Django-managed copy in "posthog" local dev DB! Example:
-- `pg_dump -h localhost -p 5432 -U posthog -s -t posthog_person posthog`
--

CREATE TABLE IF NOT EXISTS posthog_person (
    id bigint PRIMARY KEY,
    created_at timestamp with time zone NOT NULL,
    properties_last_updated_at jsonb,
    properties_last_operation jsonb,
    properties jsonb NOT NULL,
    is_identified boolean NOT NULL,
    uuid uuid NOT NULL,
    version bigint,
    is_user_id integer,
    team_id integer NOT NULL
);

CREATE INDEX posthog_per_team_id_idx ON posthog_person USING btree (team_id, id DESC);

CREATE INDEX posthog_person_email ON posthog_person USING btree (((properties ->> 'email'::text)));

CREATE INDEX posthog_person_is_user_id_idx ON posthog_person USING btree (is_user_id);

CREATE INDEX posthog_person_team_id_idx ON posthog_person USING btree (team_id);

CREATE INDEX posthog_person_uuid_idx ON posthog_person USING btree (uuid);

--
-- posthog_team table (keep in sync w/Django-managed copy in "posthog" local dev DB! Example:
-- `pg_dump -h localhost -p 5432 -U posthog -s -t posthog_team posthog`
--

CREATE TABLE IF NOT EXISTS posthog_team (
    id integer PRIMARY KEY,
    uuid uuid NOT NULL,
    api_token character varying(200) NOT NULL,
    app_urls character varying(200)[] NOT NULL,
    name character varying(200) NOT NULL,
    slack_incoming_webhook character varying(500),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    anonymize_ips boolean NOT NULL,
    completed_snippet_onboarding boolean NOT NULL,
    ingested_event boolean NOT NULL,
    session_recording_opt_in boolean NOT NULL,
    capture_console_log_opt_in boolean,
    signup_token character varying(200),
    is_demo boolean NOT NULL,
    access_control boolean NOT NULL,
    inject_web_apps boolean,
    test_account_filters jsonb NOT NULL,
    test_account_filters_default_checked boolean,
    path_cleaning_filters jsonb,
    timezone character varying(240) NOT NULL,
    data_attributes jsonb NOT NULL,
    person_display_name_properties character varying(400)[],
    live_events_columns text[],
    recording_domains character varying(200)[],
    correlation_config jsonb,
    session_recording_retention_period_days integer,
    plugins_opt_in boolean NOT NULL,
    opt_out_capture boolean NOT NULL,
    event_names jsonb NOT NULL,
    event_names_with_usage jsonb NOT NULL,
    event_properties jsonb NOT NULL,
    event_properties_with_usage jsonb NOT NULL,
    event_properties_numerical jsonb NOT NULL,
    organization_id uuid NOT NULL,
    primary_dashboard_id integer,
    capture_performance_opt_in boolean,
    session_recording_version character varying(24),
    autocapture_opt_out boolean,
    autocapture_exceptions_opt_in boolean,
    extra_settings jsonb,
    autocapture_exceptions_errors_to_ignore jsonb,
    has_completed_onboarding_for jsonb,
    week_start_day smallint,
    surveys_opt_in boolean,
    session_recording_linked_flag jsonb,
    session_recording_minimum_duration_milliseconds integer,
    session_recording_sample_rate numeric(3,2),
    external_data_workspace_id character varying(400),
    session_recording_network_payload_capture_config jsonb,
    external_data_workspace_last_synced_at timestamp with time zone,
    session_replay_config jsonb,
    project_id bigint,
    heatmaps_opt_in boolean,
    modifiers jsonb,
    autocapture_web_vitals_opt_in boolean,
    autocapture_web_vitals_allowed_metrics jsonb,
    survey_config jsonb,
    session_recording_url_trigger_config jsonb[],
    person_processing_opt_out boolean,
    session_recording_url_blocklist_config jsonb[],
    capture_dead_clicks boolean,
    session_recording_event_trigger_config text[],
    cookieless_server_hash_mode smallint,
    default_data_theme integer,
    human_friendly_comparison_periods boolean,
    flags_persistence_default boolean,
    revenue_tracking_config jsonb,
    api_query_rate_limit character varying(32),
    onboarding_tasks jsonb,
    session_recording_masking_config jsonb,

    CONSTRAINT project_id_is_not_null CHECK ((project_id IS NOT NULL)),
    CONSTRAINT posthog_team_api_token_idx_uniq UNIQUE (api_token),
    CONSTRAINT posthog_team_uuid_idx_uniq UNIQUE (uuid)
);

CREATE INDEX posthog_team_api_token_idx_like ON posthog_team USING btree (api_token varchar_pattern_ops);

CREATE INDEX posthog_team_organization_id_idx ON posthog_team USING btree (organization_id);

CREATE INDEX posthog_team_primary_dashboard_id_idx ON posthog_team USING btree (primary_dashboard_id);

CREATE INDEX posthog_team_project_id_idx ON posthog_team USING btree (project_id);

--
-- posthog_persondistinctid table (keep in sync w/Django-managed copy in "posthog" local dev DB! Example:
-- `pg_dump -h localhost -p 5432 -U posthog -s -t posthog_persondistinctid posthog`
--

CREATE TABLE posthog_persondistinctid (
    id bigint PRIMARY KEY,
    distinct_id character varying(400) NOT NULL,
    version bigint,
    person_id bigint NOT NULL,
    team_id integer NOT NULL,

    CONSTRAINT "unique distinct_id for team" UNIQUE (team_id, distinct_id)
);

CREATE INDEX posthog_persondistinctid_person_id_idx ON public.posthog_persondistinctid USING btree (person_id);


