/**
 * Per-env-var dev defaults shared by every agent service config loader.
 *
 * In dev (`NODE_ENV=development` or unset) and test, an unset env var picks
 * up the local-stack value. In prod (`NODE_ENV=production`) it stays
 * unset and the loader's Zod schema fails fast — no production deploy
 * silently picks up `localhost:9092`.
 *
 * Mirrors the nodejs/src/common/config.ts pattern: defaults live in code,
 * env vars override.
 */

import { config as loadDotenv } from 'dotenv'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { logger } from './logger'

function isProd(): boolean {
    return (process.env.NODE_ENV ?? '').toLowerCase() === 'production'
}

/**
 * Load the repo-root `.env` so agent services running under `pnpm
 * --filter` (cwd = `services/<name>`) pick up things like
 * `ANTHROPIC_API_KEY` without anyone having to thread env vars through
 * `mprocs.yaml`. Walks up from `process.cwd()` looking for `.env`;
 * no-op in production.
 */
const TRACKED_KEYS = ['ANTHROPIC_API_KEY', 'KAFKA_HOSTS', 'REDIS_URL', 'POSTHOG_DATABASE_URL'] as const

function envSnapshot(env: NodeJS.ProcessEnv): Record<string, 'set' | 'unset'> {
    return Object.fromEntries(TRACKED_KEYS.map((k) => [k, env[k] ? 'set' : 'unset'])) as Record<
        (typeof TRACKED_KEYS)[number],
        'set' | 'unset'
    >
}

export function loadDevEnv(): void {
    if (isProd()) {
        return
    }
    const before = envSnapshot(process.env)
    let dir = process.cwd()
    for (let i = 0; i < 8; i++) {
        const candidate = join(dir, '.env')
        if (existsSync(candidate)) {
            const parsed = loadDotenv({ path: candidate, override: false })
            const keys = parsed.parsed ? Object.keys(parsed.parsed) : []
            const after = envSnapshot(process.env)
            logger.info({ path: candidate, keyCount: keys.length, before, after }, 'loadDevEnv picked up .env')
            return
        }
        const parent = dirname(dir)
        if (parent === dir) {
            logger.warn({ cwd: process.cwd(), envSnapshot: before }, 'loadDevEnv: no .env found walking up from cwd')
            return
        }
        dir = parent
    }
    logger.warn({ cwd: process.cwd(), envSnapshot: before }, 'loadDevEnv: gave up walking up from cwd')
}

/** Return `value` if set; otherwise `dev` when not in production. */
export function devDefault<T extends string | undefined>(value: T, dev: string): string | T {
    if (value !== undefined && value !== '') {
        return value
    }
    return isProd() ? value : dev
}

/** Local-dev defaults consumed by `devDefault`. Centralized so tests stay
 *  honest and the dev stack only has one place to change. */
export const AGENT_DEV_DEFAULTS = {
    /** Main posthog Postgres (the same DSN Django + nodejs use locally). */
    posthogDatabaseUrl: 'postgres://posthog:posthog@localhost:5432/posthog',
    /** Dedicated queue DB for session jobs. */
    agentRuntimeQueueDatabaseUrl: 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue',
    /** Fernet key list matching Django's local `ENCRYPTION_SALT_KEYS`. */
    encryptionSaltKeys: '00beef0000beef0000beef0000beef00',
    /** Local Redis (bus + future caches). */
    redisUrl: 'redis://localhost:6379/0',
    /** Local Kafka. */
    kafkaHosts: 'localhost:9092',
    /** Shared key between Django and agent-janitor for internal endpoints. */
    agentInternalApiSharedKey: 'dev-shared-key',
} as const
