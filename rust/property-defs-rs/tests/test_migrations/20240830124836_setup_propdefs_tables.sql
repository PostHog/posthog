-- These mimic the posthog main-db property, event, hostdefinition, and event-property tables, and are only used
-- for testing (so we can use `sqlx::test`)

CREATE TABLE IF NOT EXISTS posthog_eventdefinition (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    volume_30_day INTEGER,
    query_usage_30_day INTEGER,
    team_id INTEGER NOT NULL,
    project_id BIGINT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT posthog_eventdefinition_team_id_name_80fa0b87_uniq UNIQUE (team_id, name)
);

CREATE UNIQUE INDEX IF NOT EXISTS event_definition_proj_uniq ON posthog_eventdefinition (coalesce(project_id, team_id), name);

CREATE TABLE IF NOT EXISTS posthog_propertydefinition (
    id UUID PRIMARY KEY,
    name VARCHAR(400) NOT NULL,
    is_numerical BOOLEAN NOT NULL,
    query_usage_30_day INTEGER,
    property_type VARCHAR(50),
    property_type_format VARCHAR(50),
    volume_30_day INTEGER,
    team_id INTEGER NOT NULL,
    project_id BIGINT NULL,
    group_type_index SMALLINT,
    type SMALLINT NOT NULL DEFAULT 1
);

CREATE UNIQUE INDEX IF NOT EXISTS posthog_propertydefinition_uniq ON posthog_propertydefinition (team_id, name, type, coalesce(group_type_index, -1));
CREATE UNIQUE INDEX IF NOT EXISTS posthog_propdef_proj_uniq ON posthog_propertydefinition (coalesce(project_id, team_id), name, type, coalesce(group_type_index, -1));


CREATE TABLE IF NOT EXISTS posthog_eventproperty (
    id SERIAL PRIMARY KEY,
    event VARCHAR(400)NOT NULL,
    property VARCHAR(400) NOT NULL,
    team_id INTEGER NOT NULL,
    project_id BIGINT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS posthog_event_property_unique_team_event_property ON posthog_eventproperty (team_id, event, property);
CREATE UNIQUE INDEX IF NOT EXISTS posthog_event_property_unique_proj_event_property ON posthog_eventproperty (coalesce(project_id, team_id), event, property);

CREATE TABLE IF NOT EXISTS posthog_grouptypemapping (
    id UUID PRIMARY KEY,
    group_type VARCHAR(400) NOT NULL,
    group_type_index INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    project_id BIGINT NULL,
    name_plural VARCHAR(400) NULL,
    name_singular VARCHAR(400) NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS posthog_grouptypemapping_pkey ON posthog_grouptypemapping (id);
CREATE UNIQUE INDEX IF NOT EXISTS "unique group types for project" ON posthog_grouptypemapping USING btree (project_id, group_type);
CREATE UNIQUE INDEX IF NOT EXISTS "unique event column indexes for project" ON posthog_grouptypemapping USING btree (project_id, group_type_index);

CREATE TABLE IF NOT EXISTS posthog_user (
    id SERIAL PRIMARY KEY,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL,
    uuid uuid NOT NULL,
    email character varying(254) NOT NULL,
    temporary_token character varying(200),
    distinct_id character varying(200),
    email_opt_in boolean,
    partial_notification_settings jsonb,
    anonymize_data boolean,
    toolbar_mode character varying(200),
    events_column_config jsonb NOT NULL,
    current_organization_id uuid,
    current_team_id integer,
    is_email_verified boolean,
    pending_email character varying(254),
    requested_password_reset_at timestamp with time zone,
    has_seen_product_intro_for jsonb,
    theme_mode character varying(20),
    strapi_id smallint,
    hedgehog_config jsonb,
    role_at_organization character varying(64),
    CONSTRAINT posthog_user_strapi_id_check CHECK ((strapi_id >= 0))
);

CREATE UNIQUE INDEX IF NOT EXISTS posthog_user_distinct_id_uniq ON posthog_user USING btree (distinct_id);
CREATE UNIQUE INDEX IF NOT EXISTS posthog_user_email_uniq ON posthog_user USING btree (email);
CREATE UNIQUE INDEX IF NOT EXISTS posthog_user_tmp_token ON posthog_user USING btree (temporary_token);
CREATE UNIQUE INDEX IF NOT EXISTS posthog_user_uuid ON posthog_user USING btree (uuid);
-- NOTE: for now, I left off some indices that aren't relevant to property defs query testing

CREATE TABLE ee_enterprisepropertydefinition (
    propertydefinition_ptr_id UUID PRIMARY KEY,
    description text,
    deprecated_tags character varying(32)[],
    updated_at timestamp with time zone NOT NULL,
    updated_by_id integer,
    tags character varying(32)[],
    verified boolean NOT NULL,
    verified_at timestamp with time zone,
    verified_by_id integer
);

CREATE INDEX ee_enterprisepropertydefinition_updated_by_id ON ee_enterprisepropertydefinition USING btree (updated_by_id);
CREATE INDEX ee_enterprisepropertydefinition_verified_by_id ON ee_enterprisepropertydefinition USING btree (verified_by_id);
-- NOTE: for now, I left off some indices that aren't relevant to property defs query testing
