import { ApiClient } from '@/api/client'
import { CUSTOM_BASE_URL } from '@/lib/constants'
import type { ScopedCache } from '@/lib/utils/cache/ScopedCache'
import type { CloudRegion, State } from '@/tools/types'
import type { Config } from '../config'

const PUBLIC_API_URL_US = 'https://us.posthog.com'
const PUBLIC_API_URL_EU = 'https://eu.posthog.com'

export class RegionService {
    constructor(private config: Config) {}

    async detectRegion(apiToken: string): Promise<CloudRegion | undefined> {
        const usClient = new ApiClient({
            apiToken,
            baseUrl: PUBLIC_API_URL_US,
        })

        const euClient = new ApiClient({
            apiToken,
            baseUrl: PUBLIC_API_URL_EU,
        })

        const [usResult, euResult] = await Promise.all([usClient.users().me(), euClient.users().me()])

        if (usResult.success) {
            return 'us'
        }

        if (euResult.success) {
            return 'eu'
        }

        return undefined
    }

    async getApiBaseUrl(apiToken: string, cache: ScopedCache<State>): Promise<string> {
        if (CUSTOM_BASE_URL) {
            return CUSTOM_BASE_URL
        }

        let region = await cache.get('region')

        if (!region) {
            region = await this.detectRegion(apiToken)
            if (region) {
                await cache.set('region', region)
            }
        }

        if (region === 'eu') {
            return this.config.internalApiUrlEu || PUBLIC_API_URL_EU
        }

        return this.config.internalApiUrlUs || PUBLIC_API_URL_US
    }
}
