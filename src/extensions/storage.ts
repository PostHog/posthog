import { PluginConfig, PluginsServer } from '../types'
import { StorageExtension } from '@posthog/plugin-scaffold'

export function createStorage(server: PluginsServer, pluginConfig: PluginConfig): StorageExtension {
    const get = async function (key: string, defaultValue: unknown): Promise<unknown> {
        const result = await server.db.query(
            'SELECT * FROM posthog_pluginstorage WHERE "plugin_config_id"=$1 AND "key"=$2 LIMIT 1',
            [pluginConfig.id, key]
        )
        return result?.rows.length === 1 ? JSON.parse(result.rows[0].value) : defaultValue
    }
    const set = async function (key: string, value: unknown): Promise<void> {
        if (typeof value === 'undefined') {
            await server.db.query('DELETE FROM posthog_pluginstorage WHERE "plugin_config_id"=$1 AND "key"=$2', [
                pluginConfig.id,
                key,
            ])
        } else {
            await server.db.query(
                `
                    INSERT INTO posthog_pluginstorage ("plugin_config_id", "key", "value") 
                    VALUES ($1, $2, $3)
                    ON CONFLICT ("plugin_config_id", "key") 
                    DO UPDATE SET value = $3
                `,
                [pluginConfig.id, key, JSON.stringify(value)]
            )
        }
    }

    return {
        get,
        set,
    }
}
