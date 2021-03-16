import { CacheExtension } from '@posthog/plugin-scaffold'

import { PluginsServer } from '../../types'

export function createCache(server: PluginsServer, pluginId: number, teamId: number): CacheExtension {
    const getKey = (key: string) => `@plugin/${pluginId}/${typeof teamId === 'undefined' ? '@all' : teamId}/${key}`
    return {
        set: async function (key, value, ttlSeconds, options) {
            return await server.db.redisSet(getKey(key), value, ttlSeconds, options)
        },
        get: async function (key, defaultValue, options) {
            return await server.db.redisGet(getKey(key), defaultValue, options)
        },
        incr: async function (key) {
            return await server.db.redisIncr(getKey(key))
        },
        expire: async function (key, ttlSeconds) {
            return await server.db.redisExpire(getKey(key), ttlSeconds)
        },
    }
}
