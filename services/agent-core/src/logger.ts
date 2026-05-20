import pino, { ChildLoggerOptions, Logger as PinoLogger, LoggerOptions } from 'pino'

const level = process.env.LOG_LEVEL ?? (process.env.NODE_ENV === 'test' ? 'silent' : 'info')

const options: LoggerOptions = {
    level,
    base: { pkg: '@posthog/agent-core' },
    timestamp: pino.stdTimeFunctions.isoTime,
    formatters: {
        level: (label) => ({ level: label }),
    },
    // Render Errors with message + stack + nested cause when passed as `err`
    // or `error`. Without this, pino spreads Error's (non-enumerable) props
    // and emits `{}`.
    serializers: {
        err: pino.stdSerializers.err,
        error: pino.stdSerializers.err,
    },
}

const LEVEL_METHODS = ['fatal', 'error', 'warn', 'info', 'debug', 'trace'] as const

/**
 * Patch pino's level methods to accept either arg order:
 *   - canonical: `logger.info({ ctx }, 'message')`
 *   - inverted:  `logger.info('message', { ctx })`
 *
 * Pino itself silently treats the inverted form as `(msg, interp)` and drops
 * the object, which is the source of half our "log has no context" bugs. The
 * swap is harmless when called with the canonical form because we only swap
 * when arg0 is a string AND arg1 is a plain non-array, non-null object.
 *
 * Patches `.child()` recursively so child loggers inherit the convention.
 */
function patchLevelMethods<T extends PinoLogger>(target: T): T {
    for (const method of LEVEL_METHODS) {
        const original = target[method].bind(target) as (...args: unknown[]) => void
        const patched = (...args: unknown[]): void => {
            if (
                args.length >= 2 &&
                typeof args[0] === 'string' &&
                typeof args[1] === 'object' &&
                args[1] !== null &&
                !Array.isArray(args[1])
            ) {
                original(args[1], args[0], ...args.slice(2))
                return
            }
            original(...args)
        }
        ;(target as unknown as Record<string, unknown>)[method] = patched
    }

    const originalChild = target.child.bind(target)
    ;(target as unknown as Record<string, unknown>).child = (
        bindings: Record<string, unknown>,
        opts?: ChildLoggerOptions
    ): PinoLogger => patchLevelMethods(originalChild(bindings, opts))

    return target
}

export const logger: PinoLogger = patchLevelMethods(pino(options))

export type Logger = PinoLogger
