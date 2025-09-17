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
    created_at TIMESTAMPTZ NOT NULL
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

CREATE UNIQUE INDEX IF NOT EXISTS posthog_propdef_proj_uniq ON posthog_propertydefinition (coalesce(project_id, team_id), name, type, coalesce(group_type_index, -1));


CREATE TABLE IF NOT EXISTS posthog_eventproperty (
    id SERIAL PRIMARY KEY,
    event VARCHAR(400)NOT NULL,
    property VARCHAR(400) NOT NULL,
    team_id INTEGER NOT NULL,
    project_id BIGINT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS posthog_event_property_unique_proj_event_property ON posthog_eventproperty (coalesce(project_id, team_id), event, property);

CREATE TABLE IF NOT EXISTS posthog_grouptypemapping (
    id integer PRIMARY KEY,
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
