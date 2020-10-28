import { PluginsServer } from '../types'

export function createCache(server: PluginsServer, pluginName: string, teamId: number) {
    const getKey = (key: string) => `@plugin/${pluginName}/${teamId}/${key}`
    return {
        set: function (key, value) {
            server.redis.set(getKey(key), JSON.stringify(value))
        },
        get: async function (key, defaultValue) {
            const value = await server.redis.get(getKey(key))
            if (typeof value === 'undefined') {
                return defaultValue
            }
            try {
                return JSON.parse(value)
            } catch (SyntaxError) {
                return null
            }
        },
    }
}
