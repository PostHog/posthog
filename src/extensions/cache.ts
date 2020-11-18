import { PluginsServer } from '../types'
import { CacheExtension } from 'posthog-plugins'

export function createCache(server: PluginsServer, pluginName: string, teamId: number): CacheExtension {
    const getKey = (key: string) => `@plugin/${pluginName}/${typeof teamId === 'undefined' ? '@all' : teamId}/${key}`
    return {
        set: function (key: string, value: unknown): void {
            server.redis.set(getKey(key), JSON.stringify(value))
        },
        get: async function (key: string, defaultValue: unknown): Promise<unknown> {
            const value = await server.redis.get(getKey(key))
            if (typeof value === 'undefined') {
                return defaultValue
            }
            try {
                return value ? JSON.parse(value) : null
            } catch (e) {
                return null
            }
        },
    }
}
