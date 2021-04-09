import { processError } from '../../shared/error'
import { PluginsServer } from '../../types'

export async function teardownPlugins(server: PluginsServer): Promise<void> {
    const { pluginConfigs } = server

    const teardownPromises: Promise<void>[] = []
    for (const [id, pluginConfig] of pluginConfigs) {
        if (pluginConfig.vm) {
            const teardownPlugin = await pluginConfig.vm.getTeardownPlugin()
            if (teardownPlugin) {
                teardownPromises.push(
                    (async () => {
                        try {
                            await teardownPlugin()
                        } catch (error) {
                            await processError(server, pluginConfig, error)
                        }
                    })()
                )
            }
        }
    }

    await Promise.all(teardownPromises)
}
