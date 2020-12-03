import { PluginConfig, PluginError, PluginsServer } from './types'
import { PluginEvent } from 'posthog-plugins'
import { setError } from './sql'

export async function processError(
    server: PluginsServer,
    pluginConfig: PluginConfig,
    error: Error | string,
    event?: PluginEvent | null
): Promise<void> {
    console.error(error)

    const errorJson: PluginError =
        typeof error === 'string'
            ? {
                  message: error,
                  time: new Date().toISOString(),
              }
            : {
                  message: error.message,
                  time: new Date().toISOString(),
                  name: error.name,
                  stack: error.stack,
                  event: event,
              }

    await setError(server, errorJson, pluginConfig)
}

export async function clearError(server: PluginsServer, pluginConfig: PluginConfig): Promise<void> {
    await setError(server, null, pluginConfig)
}
