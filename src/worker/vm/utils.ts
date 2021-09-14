import { QueryResult } from 'pg'

import { PluginConfig } from '../../types'
import { DB } from '../../utils/db/db'

// This assumes the value stored at `key` can be cast to a Postgres numeric type
export const postgresIncrement = async (
    db: DB,
    pluginConfigId: PluginConfig['id'],
    key: string,
    incrementBy = 1
): Promise<number> => {
    const incrementResult = await db.postgresQuery(
        `
        INSERT INTO posthog_pluginstorage (plugin_config_id, key, value)
        VALUES ($1, $2, $3)
        ON CONFLICT ("plugin_config_id", "key")
        DO UPDATE SET value = posthog_pluginstorage.value::numeric + ${incrementBy}
        RETURNING value
        `,
        [pluginConfigId, key, incrementBy],
        'postgresIncrement'
    )

    return incrementResult.rows[0].value
}

export const postgresSetOnce = async (
    db: DB,
    pluginConfigId: PluginConfig['id'],
    key: string,
    value: number
): Promise<void> => {
    const se = await db.postgresQuery(
        `
        INSERT INTO posthog_pluginstorage (plugin_config_id, key, value)
        VALUES ($1, $2, $3)
        ON CONFLICT ("plugin_config_id", "key")
        DO NOTHING
         `,
        [pluginConfigId, key, value],
        'postgresSetOnce'
    )
}

export const postgresGet = async (
    db: DB,
    pluginConfigId: PluginConfig['id'],
    key: string
): Promise<QueryResult<any>> => {
    return await db.postgresQuery(
        'SELECT * FROM posthog_pluginstorage WHERE "plugin_config_id"=$1 AND "key"=$2 LIMIT 1',
        [pluginConfigId, key],
        'storageGet'
    )
}

export const addPublicJobIfNotExists = async (
    db: DB,
    pluginId: number,
    jobName: string,
    jobPayloadJson: Record<string, any>
): Promise<void> => {
    await db.postgresQuery(
        `
        UPDATE posthog_plugin
        SET public_jobs = public_jobs || $1::jsonb
        WHERE id = $2
        AND (SELECT (public_jobs->$3) IS NULL)
         `,
        [JSON.stringify({ [jobName]: jobPayloadJson }), pluginId, jobName],
        'addPublicJobIfNotExists'
    )
}
