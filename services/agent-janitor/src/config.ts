import { z } from 'zod'

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
})

export type JanitorServiceConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): JanitorServiceConfig {
    return ConfigSchema.parse({
        port: env.PORT,
        queueDbUrl: env.AGENT_RUNTIME_QUEUE_DATABASE_URL,
        internalApiSharedKey: env.AGENT_INTERNAL_API_SHARED_KEY,
        janitorIntervalMs: env.JANITOR_INTERVAL_MS,
        janitorStallTimeoutMs: env.JANITOR_STALL_TIMEOUT_MS,
        janitorMaxTouchCount: env.JANITOR_MAX_TOUCH_COUNT,
        janitorCleanupGraceMs: env.JANITOR_CLEANUP_GRACE_MS,
    })
}
