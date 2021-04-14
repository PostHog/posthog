import { GeoIPExtension } from '@posthog/plugin-scaffold'

import { PluginsServer } from '../../../types'
import { fetchIpLocationInternally } from '../../mmdb'

export function createGeoIp(server: PluginsServer): GeoIPExtension {
    return {
        locate: async function (ipAddress) {
            return await fetchIpLocationInternally(ipAddress, server)
        },
    }
}
