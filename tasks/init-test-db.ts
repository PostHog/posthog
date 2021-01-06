import { createServer } from '../src/server'

async function task() {
    const [server, closeServer] = await createServer()

    await server.db.query(createTeam)
    await server.db.query(createPlugin)
    await server.db.query(createPluginConfig)
    await server.db.query(createPluginAttachment)
    await server.db.query(createPluginStorage)

    await closeServer()
}

const createTeam = `
    CREATE TABLE posthog_team
    (
        id            serial  NOT NULL
            CONSTRAINT posthog_team_pkey
                PRIMARY KEY,
        name          varchar(200)
    );
`

const createPlugin = `
    CREATE TABLE posthog_plugin
    (
        id            serial  NOT NULL
            CONSTRAINT posthog_plugin_pkey
                PRIMARY KEY,
        name          varchar(200),
        description   text,
        url           varchar(800),
        config_schema jsonb   NOT NULL,
        tag           varchar(200),
        archive       bytea,
        from_json     boolean NOT NULL,
        from_web      boolean NOT NULL,
        error         jsonb,
        plugin_type     varchar(200),
        source          text
    );
`

const createPluginAttachment = `
    CREATE TABLE posthog_pluginattachment
    (
        id               serial       NOT NULL
            CONSTRAINT posthog_pluginattachment_pkey
                PRIMARY KEY,
        key              varchar(200) NOT NULL,
        content_type     varchar(200) NOT NULL,
        file_name        varchar(200) NOT NULL,
        file_size        integer      NOT NULL,
        contents         bytea        NOT NULL,
        plugin_config_id integer      NOT NULL
            CONSTRAINT posthog_pluginattach_plugin_config_id_cc94a1b9_fk_posthog_p
                REFERENCES posthog_pluginconfig
                DEFERRABLE INITIALLY DEFERRED,
        team_id          integer
            CONSTRAINT posthog_pluginattachment_team_id_415eacc7_fk_posthog_team_id
                REFERENCES posthog_team
                DEFERRABLE INITIALLY DEFERRED
    );
    
    CREATE INDEX posthog_pluginattachment_plugin_config_id_cc94a1b9
        ON posthog_pluginattachment (plugin_config_id);
    
    CREATE INDEX posthog_pluginattachment_team_id_415eacc7
        ON posthog_pluginattachment (team_id);
`

const createPluginConfig = `
    CREATE TABLE posthog_pluginconfig
    (
        id        serial  NOT NULL
            CONSTRAINT posthog_pluginconfig_pkey
                PRIMARY KEY,
        team_id   integer
            CONSTRAINT posthog_pluginconfig_team_id_71185766_fk_posthog_team_id
                REFERENCES posthog_team
                DEFERRABLE INITIALLY DEFERRED,
        plugin_id integer NOT NULL
            CONSTRAINT posthog_pluginconfig_plugin_id_d014ca1c_fk_posthog_plugin_id
                REFERENCES posthog_plugin
                DEFERRABLE INITIALLY DEFERRED,
        enabled   boolean NOT NULL,
        "order"   integer,
        config    jsonb   NOT NULL,
        error     jsonb
    );
    
    CREATE INDEX posthog_pluginconfig_team_id_71185766
        ON posthog_pluginconfig (team_id);
    
    CREATE INDEX posthog_pluginconfig_plugin_id_d014ca1c
        ON posthog_pluginconfig (plugin_id);
`

const createPluginStorage = `
    CREATE TABLE posthog_pluginstorage (
        id serial NOT NULL CONSTRAINT posthog_pluginstorage_pkey PRIMARY KEY,
        key varchar(200) NOT NULL,
        value text,
        plugin_config_id integer NOT NULL CONSTRAINT posthog_pluginstorag_plugin_config_id_6744363a_fk_posthog_p
        REFERENCES posthog_pluginconfig DEFERRABLE INITIALLY DEFERRED
    );

    CREATE INDEX posthog_pluginstorage_plugin_config_id_6744363a ON posthog_pluginstorage (plugin_config_id);

    CREATE UNIQUE INDEX posthog_unique_plugin_storage_key ON posthog_pluginstorage (plugin_config_id int4_ops, KEY text_ops);
`

task()
