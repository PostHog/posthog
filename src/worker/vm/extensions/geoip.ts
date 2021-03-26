import { GeoIPExtension } from '@posthog/plugin-scaffold'

import { PluginsServer } from '../../../types'

function throwMmdbUnavailable(): never {
    throw new Error('IP location capabilities are not available in this PostHog instance!')
}

export function createGeoIp(server: PluginsServer): GeoIPExtension {
    return {
        locate: function (ip) {
            if (!server.mmdb) {
                throwMmdbUnavailable()
            }
            try {
                return server.mmdb.city(ip)
            } catch {
                return null
            }
        },
    }
}
