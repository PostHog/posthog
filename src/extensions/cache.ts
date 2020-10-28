import { PluginsServer } from '../types'

export function createCache(server: PluginsServer, pluginName: string, teamId: number) {
    const getKey = (key: string) => `@plugin/${pluginName}/${typeof teamId === 'undefined' ? '@all' : teamId}/${key}`
    return {
        set: function (key: string, value: any) {
            server.redis.set(getKey(key), JSON.stringify(value))
        },
        get: async function (key: string, defaultValue: any) {
            const value = await server.redis.get(getKey(key))
            if (typeof value === 'undefined') {
                return defaultValue
            }
            try {
                return value ? JSON.parse(value) : null
            } catch (SyntaxError) {
                return null
            }
        },
    }
}
