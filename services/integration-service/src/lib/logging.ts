// Leveled logger backed by pino.
//
// Never constructs a pino transport: prod runs the esbuild bundle, and a transport spawns
// a worker needing lib/worker.js + __dirname, neither of which exists in a single-file ESM
// bundle. Dev pipes this JSON through the pino-pretty CLI instead.

import pino from 'pino'

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

function resolveLevel(): LogLevel {
    const explicit = process.env.INTEGRATION_SERVICE_LOG_LEVEL?.toLowerCase()
    if (explicit === 'debug' || explicit === 'info' || explicit === 'warn' || explicit === 'error') {
        return explicit
    }
    switch (process.env.NODE_ENV) {
        case 'production':
            return 'info'
        case 'test':
            return 'warn'
        default:
            return 'debug'
    }
}

const pinoOptions: pino.LoggerOptions = { level: resolveLevel() }
if (process.env.NODE_ENV === 'production') {
    pinoOptions.formatters = { level: (label) => ({ level: label }) }
}
const pinoLogger = pino(pinoOptions)

export const logger = {
    debug: (event: string, fields?: Record<string, unknown>): void => pinoLogger.debug({ event, ...fields }),
    info: (event: string, fields?: Record<string, unknown>): void => pinoLogger.info({ event, ...fields }),
    warn: (event: string, fields?: Record<string, unknown>): void => pinoLogger.warn({ event, ...fields }),
    error: (event: string, fields?: Record<string, unknown>): void => pinoLogger.error({ event, ...fields }),
}
