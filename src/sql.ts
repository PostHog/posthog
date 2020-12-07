import { Plugin, PluginAttachmentDB, PluginConfig, PluginError, PluginsServer } from './types'

// This nice "mocking" system is used since we want to mock data in worker threads.
// Jest mocks don't penetrate that far. Improvements welcome.
function areWeTestingWithJest() {
    return process.env.JEST_WORKER_ID !== undefined
}

export async function getPluginRows(server: PluginsServer): Promise<Plugin[]> {
    if (areWeTestingWithJest() && server.__jestMock?.getPluginRows) {
        return server.__jestMock?.getPluginRows
    }
    const { rows: pluginRows }: { rows: Plugin[] } = await server.db.query(
        "SELECT * FROM posthog_plugin WHERE id in (SELECT plugin_id FROM posthog_pluginconfig WHERE enabled='t' GROUP BY plugin_id)"
    )
    return pluginRows
}

export async function getPluginAttachmentRows(server: PluginsServer): Promise<PluginAttachmentDB[]> {
    if (areWeTestingWithJest() && server.__jestMock?.getPluginAttachmentRows) {
        return server.__jestMock?.getPluginAttachmentRows
    }
    const { rows }: { rows: PluginAttachmentDB[] } = await server.db.query(
        "SELECT * FROM posthog_pluginattachment WHERE plugin_config_id in (SELECT id FROM posthog_pluginconfig WHERE enabled='t')"
    )
    return rows
}

export async function getPluginConfigRows(server: PluginsServer): Promise<PluginConfig[]> {
    if (areWeTestingWithJest() && server.__jestMock?.getPluginConfigRows) {
        return server.__jestMock?.getPluginConfigRows
    }
    const { rows }: { rows: PluginConfig[] } = await server.db.query(
        "SELECT * FROM posthog_pluginconfig WHERE enabled='t'"
    )
    return rows
}

export async function setError(
    server: PluginsServer,
    pluginError: PluginError | null,
    pluginConfig: PluginConfig
): Promise<void> {
    await server.db.query('UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2', [pluginError, pluginConfig.id])
}
