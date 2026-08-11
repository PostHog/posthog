// Entry point: load config, construct the server, start it.

import { loadConfig } from './lib/config.js'
import { logger } from './lib/logging.js'
import { IntegrationServer } from './server.js'

new IntegrationServer(loadConfig()).start().catch((err: unknown) => {
    logger.error('fatal', { error: err instanceof Error ? err.message : String(err) })
    process.exit(1)
})
