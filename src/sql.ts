import { Plugin, PluginAttachmentDB, PluginConfig, PluginConfigId, PluginError, PluginsServer } from './types'

export async function getPluginRows(server: PluginsServer): Promise<Plugin[]> {
    const { rows: pluginRows }: { rows: Plugin[] } = await server.db.query(
        `SELECT posthog_plugin.* FROM posthog_plugin WHERE id in
            (SELECT posthog_pluginconfig.plugin_id
                FROM posthog_pluginconfig
                LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
                WHERE (posthog_team.id IS NULL OR posthog_team.plugins_opt_in='t') AND posthog_pluginconfig.enabled='t'
                GROUP BY posthog_pluginconfig.plugin_id)`
    )
    return pluginRows
}

export async function getPluginAttachmentRows(server: PluginsServer): Promise<PluginAttachmentDB[]> {
    const { rows }: { rows: PluginAttachmentDB[] } = await server.db.query(
        `SELECT posthog_pluginattachment.* FROM posthog_pluginattachment WHERE plugin_config_id in
            (SELECT posthog_pluginconfig.id
                FROM posthog_pluginconfig
                LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
                WHERE (posthog_team.id IS NULL OR posthog_team.plugins_opt_in='t') AND posthog_pluginconfig.enabled='t')`
    )
    return rows
}

export async function getPluginConfigRows(server: PluginsServer): Promise<PluginConfig[]> {
    const { rows }: { rows: PluginConfig[] } = await server.db.query(
        `SELECT posthog_pluginconfig.*
            FROM posthog_pluginconfig
            LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
            WHERE (posthog_team.id IS NULL OR posthog_team.plugins_opt_in='t') AND posthog_pluginconfig.enabled='t'`
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
