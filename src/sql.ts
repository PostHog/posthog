import { Plugin, PluginAttachmentDB, PluginConfig, PluginConfigId, PluginError, PluginsServer } from './types'

export async function getPluginRows(server: PluginsServer): Promise<Plugin[]> {
    const { rows: pluginRows }: { rows: Plugin[] } = await server.db.query(
        "SELECT * FROM posthog_plugin WHERE id in (SELECT plugin_id FROM posthog_pluginconfig WHERE enabled='t' GROUP BY plugin_id)"
    )
    return pluginRows
}

export async function getPluginAttachmentRows(server: PluginsServer): Promise<PluginAttachmentDB[]> {
    const { rows }: { rows: PluginAttachmentDB[] } = await server.db.query(
        "SELECT * FROM posthog_pluginattachment WHERE plugin_config_id in (SELECT id FROM posthog_pluginconfig WHERE enabled='t')"
    )
    return rows
}

export async function getPluginConfigRows(server: PluginsServer): Promise<PluginConfig[]> {
    const { rows }: { rows: PluginConfig[] } = await server.db.query(
        "SELECT * FROM posthog_pluginconfig WHERE enabled='t'"
    )
    return rows
}

export async function setError(
    server: PluginsServer,
    pluginError: PluginError | null,
    pluginConfig: PluginConfig | PluginConfigId
): Promise<void> {
    await server.db.query('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [
        pluginError,
        typeof pluginConfig === 'object' ? pluginConfig?.id : pluginConfig,
    ])
}
