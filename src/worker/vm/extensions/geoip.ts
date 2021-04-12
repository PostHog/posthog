import { GeoIPExtension } from '@posthog/plugin-scaffold'

import { fetchIpLocationInternally, MMDBRequestStatus } from '../../../shared/mmdb'
import { PluginsServer } from '../../../types'

export function createGeoIp(server: PluginsServer): GeoIPExtension {
    return {
        locate: async function (ipAddress) {
            return await fetchIpLocationInternally(ipAddress, server)
        },
    }
}
