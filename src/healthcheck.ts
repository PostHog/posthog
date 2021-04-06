import { defaultConfig } from './shared/config'
import { Status } from './shared/status'
import { createRedis } from './shared/utils'

const healthStatus = new Status('HLTH')

void createRedis(defaultConfig).then(async (redis) => {
    const ping = await redis.get('@posthog-plugin-server/ping')
    if (ping) {
        healthStatus.info('💚', `Redis key @posthog-plugin-server/ping found with value ${ping}`)
        process.exit(0)
    } else {
        healthStatus.error('💔', 'Redis key @posthog-plugin-server/ping not found! Plugin server seems to be offline')
        process.exit(1)
    }
})
