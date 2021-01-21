import { PluginConfig, PluginConfigId, PluginError, PluginsServer } from './types'
import { PluginEvent } from '@posthog/plugin-scaffold'
import { setError } from './sql'
import * as Sentry from '@sentry/node'
import { status } from './status'

export async function processError(
    server: PluginsServer,
    pluginConfig: PluginConfig | PluginConfigId,
    error: Error | string,
    event?: PluginEvent | null
): Promise<void> {
    Sentry.captureException(error)
    status.error('⁉️', 'An error occurred:\n', error)

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

export async function clearError(server: PluginsServer, pluginConfig: PluginConfig | PluginConfigId): Promise<void> {
    await setError(server, null, pluginConfig)
}
