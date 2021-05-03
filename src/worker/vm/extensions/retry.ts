import { PluginConfig, PluginsServer } from '../../../types'

const minRetry = process.env.NODE_ENV === 'test' ? 1 : 30

// TODO: add type to scaffold
export function createRetry(
    server: PluginsServer,
    pluginConfig: PluginConfig
): (type: string, payload: any, retry_in?: number) => Promise<void> {
    return async (type: string, payload: any, retry_in = 30) => {
        if (retry_in < minRetry || retry_in > 86400) {
            throw new Error(`Retries must happen between ${minRetry} seconds and 24 hours from now`)
        }
        const timestamp = new Date().valueOf() + retry_in * 1000
        await server.retryQueueManager.enqueue({
            type,
            payload,
            timestamp,
            pluginConfigId: pluginConfig.id,
            pluginConfigTeam: pluginConfig.team_id,
        })
    }
}
