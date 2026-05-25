import { z } from 'zod'

import { AGENT_DEV_DEFAULTS, devDefault } from '@posthog/agent-core'

const ConfigSchema = z.object({
    port: z.coerce.number().int().min(1).max(65_535).default(3031),
    queueDbUrl: z.string().min(1),
    /**
     * Shared key required on every `/internal/*` request. Django supplies it via
     * `x-internal-key`. When unset, internal routes refuse all traffic — keep the
     * service operable in dev by setting it explicitly.
     */
    internalApiSharedKey: z.string().min(1).optional(),
    janitorIntervalMs: z.coerce.number().int().min(0).default(10_000),
    janitorStallTimeoutMs: z.coerce.number().int().min(0).default(30_000),
    janitorMaxTouchCount: z.coerce.number().int().min(1).default(3),
    janitorCleanupGraceMs: z.coerce.number().int().min(0).default(10_000),
    /** PostHog DB URL — required to sweep sandbox rows; same string the agent-runner uses. */
    posthogDbUrl: z.string().min(1).optional(),
    /** How often to sweep stale sandbox rows. Set to 0 to disable. */
    sandboxJanitorIntervalMs: z.coerce.number().int().min(0).default(60_000),
    /**
     * A sandbox row idle this long is presumed orphaned. Must exceed the
     * per-tool wall-clock cap (30s) by enough margin to avoid reaping live
     * sandboxes mid-session.
     */
    sandboxJanitorStaleMs: z.coerce
        .number()
        .int()
        .min(60_000)
        .default(10 * 60_000),
})

export type JanitorServiceConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): JanitorServiceConfig {
    return ConfigSchema.parse({
        port: env.PORT,
        queueDbUrl: devDefault(env.AGENT_RUNTIME_QUEUE_DATABASE_URL, AGENT_DEV_DEFAULTS.agentRuntimeQueueDatabaseUrl),
        internalApiSharedKey: devDefault(
            env.AGENT_INTERNAL_API_SHARED_KEY,
            AGENT_DEV_DEFAULTS.agentInternalApiSharedKey
        ),
        janitorIntervalMs: env.JANITOR_INTERVAL_MS,
        janitorStallTimeoutMs: env.JANITOR_STALL_TIMEOUT_MS,
        janitorMaxTouchCount: env.JANITOR_MAX_TOUCH_COUNT,
        janitorCleanupGraceMs: env.JANITOR_CLEANUP_GRACE_MS,
        posthogDbUrl: devDefault(env.POSTHOG_DATABASE_URL, AGENT_DEV_DEFAULTS.posthogDatabaseUrl),
        sandboxJanitorIntervalMs: env.SANDBOX_JANITOR_INTERVAL_MS,
        sandboxJanitorStaleMs: env.SANDBOX_JANITOR_STALE_MS,
    })
}
