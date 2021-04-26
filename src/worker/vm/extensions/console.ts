import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { status } from '../../../shared/status'
import { determineNodeEnv, NodeEnv, pluginDigest } from '../../../shared/utils'
import { PluginConfig, PluginLogEntrySource, PluginLogEntryType, PluginsServer } from '../../../types'

function consoleFormat(...args: unknown[]): string {
    return args
        .map((arg) => {
            const argString = String(arg)
            if (argString === '[object Object]' || Array.isArray(arg)) {
                return JSON.stringify(arg)
            }
            return argString
        })
        .join(' ')
}

export function createConsole(server: PluginsServer, pluginConfig: PluginConfig): ConsoleExtension {
    async function consolePersist(type: PluginLogEntryType, ...args: unknown[]): Promise<void> {
        if (determineNodeEnv() == NodeEnv.Development) {
            status.info('👉', `${type} in ${pluginDigest(pluginConfig.plugin!, pluginConfig.team_id)}:`, ...args)
        }

        if (!server.ENABLE_PERSISTENT_CONSOLE) {
            return
        }

        await server.db.createPluginLogEntry(
            pluginConfig,
            PluginLogEntrySource.Console,
            type,
            consoleFormat(...args),
            server.instanceId
        )
    }

    return {
        debug: (...args) => consolePersist(PluginLogEntryType.Debug, ...args),
        log: (...args) => consolePersist(PluginLogEntryType.Log, ...args),
        info: (...args) => consolePersist(PluginLogEntryType.Info, ...args),
        warn: (...args) => consolePersist(PluginLogEntryType.Warn, ...args),
        error: (...args) => consolePersist(PluginLogEntryType.Error, ...args),
    }
}
