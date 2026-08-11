// Entry point: load config, construct the server, start it.

import { loadConfig } from './lib/config'
import { logger } from './lib/logging'
import { IntegrationServer } from './server'

new IntegrationServer(loadConfig()).start().catch((err: unknown) => {
    logger.error('fatal', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
