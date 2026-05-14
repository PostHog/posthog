import pino, { Logger } from 'pino'

const level = process.env.LOG_LEVEL ?? (process.env.NODE_ENV === 'test' ? 'silent' : 'info')

export const logger: Logger = pino({
    level,
    base: { pkg: '@posthog/agent-core' },
    timestamp: pino.stdTimeFunctions.isoTime,
    formatters: {
        level: (label) => ({ level: label }),
    },
})

export type { Logger }
