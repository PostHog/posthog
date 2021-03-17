import { Plugin, PluginAttachmentDB, PluginConfig, PluginConfigId, PluginError, PluginsServer } from './types'

function pluginConfigsInForceQuery(specificField?: keyof PluginConfig): string {
    return `SELECT posthog_pluginconfig.${specificField || '*'}
       FROM posthog_pluginconfig
       LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
       LEFT JOIN posthog_organization ON posthog_organization.id = posthog_team.organization_id
       LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
       WHERE (
           (posthog_team.id IS NULL OR posthog_team.plugins_opt_in='t')
           AND posthog_pluginconfig.enabled='t' AND posthog_organization.plugins_access_level > 0
           AND (posthog_plugin.organization_id = posthog_organization.id OR posthog_plugin.is_global)
       )`
}

export async function getPluginRows(server: PluginsServer): Promise<Plugin[]> {
    const { rows: pluginRows }: { rows: Plugin[] } = await server.db.postgresQuery(
        `SELECT posthog_plugin.* FROM posthog_plugin
            WHERE id IN (${pluginConfigsInForceQuery('plugin_id')} GROUP BY posthog_pluginconfig.plugin_id)`
    )
    return pluginRows
}

export async function getPluginAttachmentRows(server: PluginsServer): Promise<PluginAttachmentDB[]> {
    const { rows }: { rows: PluginAttachmentDB[] } = await server.db.postgresQuery(
        `SELECT posthog_pluginattachment.* FROM posthog_pluginattachment
            WHERE plugin_config_id IN (${pluginConfigsInForceQuery('id')})`
    )
    return rows
}

export async function getPluginConfigRows(server: PluginsServer): Promise<PluginConfig[]> {
    const { rows }: { rows: PluginConfig[] } = await server.db.postgresQuery(pluginConfigsInForceQuery())
    return rows
}

export async function setError(
    server: PluginsServer,
    pluginError: PluginError | null,
    pluginConfig: PluginConfig | PluginConfigId
): Promise<void> {
    await server.db.postgresQuery('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [
        pluginError,
        typeof pluginConfig === 'object' ? pluginConfig?.id : pluginConfig,
    ])
}
