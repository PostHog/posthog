// Leveled logger for the integration-service, backed by pino (the PostHog Node
// house logger). Mirrors services/agent-proxy/src/lib/logging.ts.
//
// The logger never constructs a pino transport: dev and prod both run the esbuild
// bundle, and a transport would spawn a worker needing lib/worker.js + __dirname,
// neither of which exists in a single-file ESM bundle. Dev pipes this JSON through
// the pino-pretty CLI instead.
//
// Level comes from INTEGRATION_SERVICE_LOG_LEVEL (debug|info|warn|error). When unset
// it defaults by NODE_ENV: debug in local dev, info in production, warn under tests.

import pino from 'pino'

import { getEnv } from './env.js'

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

function resolveLevel(): LogLevel {
    const explicit = getEnv('INTEGRATION_SERVICE_LOG_LEVEL')?.toLowerCase()
    if (explicit === 'debug' || explicit === 'info' || explicit === 'warn' || explicit === 'error') {
        return explicit
    }
    switch (getEnv('NODE_ENV')) {
        case 'production':
            return 'info'
        case 'test':
            return 'warn'
        default:
            return 'debug'
    }
}

const pinoOptions: pino.LoggerOptions = { level: resolveLevel() }
if (getEnv('NODE_ENV') === 'production') {
    pinoOptions.formatters = { level: (label) => ({ level: label }) }
}
const pinoLogger = pino(pinoOptions)

export const logger = {
    debug: (event: string, fields?: Record<string, unknown>): void => pinoLogger.debug({ event, ...fields }),
    info: (event: string, fields?: Record<string, unknown>): void => pinoLogger.info({ event, ...fields }),
    warn: (event: string, fields?: Record<string, unknown>): void => pinoLogger.warn({ event, ...fields }),
    error: (event: string, fields?: Record<string, unknown>): void => pinoLogger.error({ event, ...fields }),
}
