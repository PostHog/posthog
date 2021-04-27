import {
    Plugin,
    PluginAttachmentDB,
    PluginConfig,
    PluginError,
    PluginLogEntrySource,
    PluginLogEntryType,
    PluginsServer,
} from '../types'

function pluginConfigsInForceQuery(specificField?: keyof PluginConfig): string {
    return `SELECT posthog_pluginconfig.${specificField || '*'}
       FROM posthog_pluginconfig
       LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
       LEFT JOIN posthog_organization ON posthog_organization.id = posthog_team.organization_id
       LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
       WHERE (
           posthog_pluginconfig.enabled='t' AND posthog_organization.plugins_access_level > 0
           AND (posthog_plugin.organization_id = posthog_organization.id OR posthog_plugin.is_global)
       )`
}

export async function getPluginRows(server: PluginsServer): Promise<Plugin[]> {
    const { rows: pluginRows }: { rows: Plugin[] } = await server.db.postgresQuery(
        `SELECT posthog_plugin.* FROM posthog_plugin
            WHERE id IN (${pluginConfigsInForceQuery('plugin_id')} GROUP BY posthog_pluginconfig.plugin_id)`,
        undefined,
        'getPluginRows'
    )
    return pluginRows
}

export async function getPluginAttachmentRows(server: PluginsServer): Promise<PluginAttachmentDB[]> {
    const { rows }: { rows: PluginAttachmentDB[] } = await server.db.postgresQuery(
        `SELECT posthog_pluginattachment.* FROM posthog_pluginattachment
            WHERE plugin_config_id IN (${pluginConfigsInForceQuery('id')})`,
        undefined,
        'getPluginAttachmentRows'
    )
    return rows
}

export async function getPluginConfigRows(server: PluginsServer): Promise<PluginConfig[]> {
    const { rows }: { rows: PluginConfig[] } = await server.db.postgresQuery(
        pluginConfigsInForceQuery(),
        undefined,
        'getPluginConfigRows'
    )
    return rows
}

export async function setError(
    server: PluginsServer,
    pluginError: PluginError | null,
    pluginConfig: PluginConfig
): Promise<void> {
    await server.db.postgresQuery(
        'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
        [pluginError, typeof pluginConfig === 'object' ? pluginConfig?.id : pluginConfig],
        'updatePluginConfigError'
    )
    if (pluginError && server.ENABLE_PERSISTENT_CONSOLE) {
        await server.db.createPluginLogEntry(
            pluginConfig,
            PluginLogEntrySource.Plugin,
            PluginLogEntryType.Error,
            pluginError.message,
            server.instanceId,
            pluginError.time
        )
    }
}
