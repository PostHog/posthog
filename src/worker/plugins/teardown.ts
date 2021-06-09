import { Hub, PluginConfig, PluginLogEntrySource, PluginLogEntryType } from '../../types'
import { processError } from '../../utils/db/error'

export async function teardownPlugins(server: Hub, pluginConfig?: PluginConfig): Promise<void> {
    const pluginConfigs = pluginConfig ? [pluginConfig] : server.pluginConfigs.values()

    const teardownPromises: Promise<void>[] = []
    for (const pluginConfig of pluginConfigs) {
        if (pluginConfig.vm) {
            pluginConfig.vm.clearRetryTimeoutIfExists()
            const teardownPlugin = await pluginConfig.vm.getTeardownPlugin()
            if (teardownPlugin) {
                teardownPromises.push(
                    (async () => {
                        try {
                            await teardownPlugin()
                            await server.db.createPluginLogEntry(
                                pluginConfig,
                                PluginLogEntrySource.System,
                                PluginLogEntryType.Info,
                                `Plugin unloaded (instance ID ${server.instanceId}).`,
                                server.instanceId
                            )
                        } catch (error) {
                            await processError(server, pluginConfig, error)
                            await server.db.createPluginLogEntry(
                                pluginConfig,
                                PluginLogEntrySource.System,
                                PluginLogEntryType.Error,
                                `Plugin failed to unload (instance ID ${server.instanceId}).`,
                                server.instanceId
                            )
                        }
                    })()
                )
            } else {
                await server.db.createPluginLogEntry(
                    pluginConfig,
                    PluginLogEntrySource.System,
                    PluginLogEntryType.Info,
                    `Plugin unloaded (instance ID ${server.instanceId}).`,
                    server.instanceId
                )
            }
        }
    }

    await Promise.all(teardownPromises)
}
