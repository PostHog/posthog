import Redis from 'ioredis'

import { defaultConfig } from './shared/config'
import { Status } from './shared/status'

const healthStatus = new Status('HLTH')

const redis = new Redis(defaultConfig.REDIS_URL).on('ready', async () => {
    const ping = await redis.get('@posthog-plugin-server/ping')
    if (ping) {
        healthStatus.info('💚', `Redis key @posthog-plugin-server/ping found with value ${ping}`)
        process.exit(0)
    } else {
        healthStatus.error('💔', 'Redis key @posthog-plugin-server/ping not found! Plugin server seems to be offline')
        process.exit(1)
    }
})
