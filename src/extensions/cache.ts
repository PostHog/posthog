import { PluginsServer } from '../types'
import { CacheExtension } from 'posthog-plugins'

export function createCache(server: PluginsServer, pluginName: string, teamId: number): CacheExtension {
    const getKey = (key: string) => `@plugin/${pluginName}/${typeof teamId === 'undefined' ? '@all' : teamId}/${key}`
    return {
        set: async function (key: string, value: unknown, ttlSeconds?: number): Promise<void> {
            if (ttlSeconds) {
                await server.redis.set(getKey(key), JSON.stringify(value), 'EX', ttlSeconds)
            } else {
                await server.redis.set(getKey(key), JSON.stringify(value))
            }
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
        incr: async function (key: string): Promise<number> {
            return await server.redis.incr(getKey(key))
        },
        expire: async function (key: string, ttlSeconds: number): Promise<boolean> {
            return (await server.redis.expire(getKey(key), ttlSeconds)) === 1
        },
    }
}
