// Leveled logger + wide-event RequestLogger for the agent-proxy.
//
// Backed by pino, the PostHog Node house logger (see nodejs/src/utils/logger.ts).
// The logger never constructs a pino transport: dev and prod both run the esbuild
// bundle, and a transport would spawn a worker needing lib/worker.js + __dirname,
// neither of which exists in a single-file ESM bundle. Instead:
//   - production: pino writes JSON with level NAMES (for log ingestion)
//   - dev: pino writes JSON with numeric levels; the `dev` npm script pipes it
//     through the pino-pretty CLI for readable, colorized output
//   - test: plain JSON (vitest does not pipe), no worker threads to leak
//
// Two complementary patterns:
//   1. Leveled logger (logger.debug/info/warn/error), imported by every module;
//      emits one line per discrete event, keyed by `event`.
//   2. RequestLogger, created once per HTTP request by the requestLog middleware;
//      accumulates fields via extend(); emitted as a single wide line at request
//      completion via logger.info('http.request', log.finish(status)).
//
// Level comes from AGENT_PROXY_LOG_LEVEL (debug|info|warn|error). When unset it
// defaults by NODE_ENV: debug in local dev, info in production, warn under tests.

import pino from 'pino'

import { getEnv } from './env.js'

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

function resolveLevel(): LogLevel {
    const explicit = getEnv('AGENT_PROXY_LOG_LEVEL')?.toLowerCase()
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

const level = resolveLevel()

// Plain pino with no transport, so the esbuild bundle stays worker-free. A
// pino-pretty transport spawns a thread-stream worker that resolves
// join(__dirname, 'lib', 'worker.js'), and __dirname does not exist in the
// single-file ESM bundle that dev and prod both run. Pretty output in dev comes
// from piping this JSON through the pino-pretty CLI in the `dev` script instead.
//
// Production emits the level NAME (for log ingestion, matching nodejs); dev and
// test keep pino's numeric levels, which the pino-pretty CLI renders natively.
const pinoOptions: pino.LoggerOptions = { level }
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

// ---------------------------------------------------------------------------
// Wide-event request logger
// ---------------------------------------------------------------------------

// Header names that must never appear in logs — values replaced with '[REDACTED]'.
// x-csrftoken and x-posthog-session-id carry per-user browser tokens that api.stream
// sends on every request, so they are redacted alongside the standard auth headers.
export const SENSITIVE_HEADERS = new Set([
    'authorization',
    'cookie',
    'x-api-key',
    'x-csrftoken',
    'x-posthog-session-id',
])

// Return a copy of `headers` with sensitive values replaced by '[REDACTED]'.
// Comparison is case-insensitive to handle both canonical and lowercased names.
export function redactHeaders(headers: Record<string, string>): Record<string, string> {
    const result: Record<string, string> = {}
    for (const [key, value] of Object.entries(headers)) {
        result[key] = SENSITIVE_HEADERS.has(key.toLowerCase()) ? '[REDACTED]' : value
    }
    return result
}

// Accumulates per-request fields from all handler layers and emits a single
// wide JSON log line at request completion.
//
// Usage in middleware:
//   const log = new RequestLogger()
//   c.set('requestLogger', log)
//   log.extend({ method, pathname, headers: redactHeaders(...) })
//   // in route handler:
//   log.extend({ run: claims.runId, project })
//   // in finally:
//   logger.info('http.request', log.finish(c.res.status))
export class RequestLogger {
    private readonly requestId: string
    private readonly startTime: number
    private data: Record<string, unknown> = {}

    constructor() {
        this.requestId = crypto.randomUUID().slice(0, 8)
        this.startTime = Date.now()
        this.data['requestId'] = this.requestId
    }

    get id(): string {
        return this.requestId
    }

    // Merge additional fields into the accumulated record. Later calls win on
    // key conflicts — route handlers overwrite middleware-set placeholders.
    extend(data: Record<string, unknown>): void {
        Object.assign(this.data, data)
    }

    // Return the accumulated record with status and durationMs appended.
    // Pass directly to logger.info as the fields argument:
    //   logger.info('http.request', log.finish(c.res.status))
    finish(status: number): Record<string, unknown> {
        return {
            ...this.data,
            status,
            durationMs: Date.now() - this.startTime,
        }
    }
}
