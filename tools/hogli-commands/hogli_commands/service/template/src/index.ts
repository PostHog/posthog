import { createLogger, serializeError, startNodeService } from '@posthog/node-service'

import { createApp } from './app.js'
import { loadConfig } from './config.js'

const bootstrapLogger = createLogger({ serviceName: '__SERVICE_NAME__' })

async function main(): Promise<void> {
    const config = loadConfig()
    const service = createApp({ logLevel: config.LOG_LEVEL })
    await startNodeService({
        service,
        hostname: config.HOST,
        port: config.PORT,
        shutdownGraceMs: config.SHUTDOWN_GRACE_MS,
    })
}

main().catch((error: unknown) => {
    bootstrapLogger.fatal({ event: 'service.start_failed', error: serializeError(error) }, 'Service failed to start')
    process.exitCode = 1
})
