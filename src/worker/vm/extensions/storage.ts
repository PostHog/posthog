import { StorageExtension } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig } from '../../../types'
import { postgresGet } from '../utils'

export function createStorage(server: Hub, pluginConfig: PluginConfig): StorageExtension {
    const get = async function (key: string, defaultValue: unknown): Promise<unknown> {
        const result = await postgresGet(server.db, pluginConfig.id, key)
        return result?.rows.length === 1 ? JSON.parse(result.rows[0].value) : defaultValue
    }
    const set = async function (key: string, value: unknown): Promise<void> {
        if (typeof value === 'undefined') {
            await del(key)
        } else {
            await server.db.postgresQuery(
                `
                    INSERT INTO posthog_pluginstorage ("plugin_config_id", "key", "value")
                    VALUES ($1, $2, $3)
                    ON CONFLICT ("plugin_config_id", "key")
                    DO UPDATE SET value = $3
                `,
                [pluginConfig.id, key, JSON.stringify(value)],
                'storageSet'
            )
        }
    }

    const del = async function (key: string): Promise<void> {
        await server.db.postgresQuery(
            'DELETE FROM posthog_pluginstorage WHERE "plugin_config_id"=$1 AND "key"=$2',
            [pluginConfig.id, key],
            'storageDelete'
        )
    }

    return {
        get,
        set,
        del,
    }
}
