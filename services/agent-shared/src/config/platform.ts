/**
 * Shared config slice for env vars every agent service reads.
 *
 * The runner / ingress / janitor each `PlatformConfigSchema.extend(...)`
 * inside their own `src/config.ts`, then call `loadServiceConfig()` once
 * at boot. This keeps cross-service defaults (`bundleRoot`, the two PG
 * URLs, `REDIS_URL`, etc.) in one place — if they ever drift, the
 * services see different DBs / bundles, which we've already hit once.
 *
 * See `docs/agent-platform/plans/typed-config-loader.md` for context.
 *
 * Service-specific schemas:
 *
 * ```ts
 * // services/agent-ingress/src/config.ts
 * export const AgentIngressConfigSchema = PlatformConfigSchema.extend({
 *     port: z.coerce.number().int().positive().default(8080).describe(...),
 *     // ... ingress-only fields ...
 * })
 * ```
 *
 * The env-key map composes the same way — each service ships its own map
 * via `extendEnvKeyMap(PLATFORM_ENV_KEY_MAP, { ... })`.
 */

import { z } from 'zod'

export const PlatformConfigSchema = z.object({
    posthogDbUrl: z
        .string()
        .url()
        .default('postgres://posthog:posthog@localhost:5432/posthog')
        .describe('Django/PostHog DB — owns agent_application + agent_revision (authoring tables).'),
    agentDbUrl: z
        .string()
        .url()
        .default('postgres://posthog:posthog@localhost:5432/agent_runtime_queue')
        .describe('Queue + sandbox-instances DB — runtime data, owned by the node side.'),
    bundleRoot: z
        .string()
        .min(1)
        .default(`${process.env.HOME ?? '/tmp'}/.posthog/agent-bundles`)
        .describe(
            'Filesystem root for agent bundles. Auto-created on boot. Production sets this to a mounted volume shared across runner + janitor.'
        ),
    redisUrl: z
        .string()
        .url()
        .optional()
        .describe(
            'When set, lifecycle events publish via RedisSessionEventBus so cross-host /listen SSE works. Without it, events stay in-process.'
        ),
    encryptionSaltKeys: z
        .string()
        .default('')
        .describe(
            'Comma-separated UTF-8 Fernet keys. Matches Django EncryptedTextField. When unset, secret resolvers are noops.'
        ),
    logLevel: z
        .enum(['debug', 'info', 'warn', 'error', 'fatal'])
        .default('info')
        .describe('pino level. Set debug to trace per-turn / per-request detail.'),
})

export type PlatformConfig = z.infer<typeof PlatformConfigSchema>

/**
 * Maps the platform-shared env var names to schema keys. Service-specific
 * loaders merge this with their own additions via `extendEnvKeyMap`.
 */
export const PLATFORM_ENV_KEY_MAP: Record<string, keyof PlatformConfig> = {
    POSTHOG_DB_URL: 'posthogDbUrl',
    AGENT_DB_URL: 'agentDbUrl',
    AGENT_BUNDLE_ROOT: 'bundleRoot',
    REDIS_URL: 'redisUrl',
    ENCRYPTION_SALT_KEYS: 'encryptionSaltKeys',
    LOG_LEVEL: 'logLevel',
}

/**
 * Compose a child env-key map onto the platform one. Type-checked so a
 * typo in the child key produces a compile error rather than silently
 * mapping nothing.
 */
export function extendEnvKeyMap<TChild>(
    base: Record<string, keyof PlatformConfig>,
    child: Record<string, keyof TChild>
): Record<string, keyof PlatformConfig | keyof TChild> {
    return { ...base, ...child }
}

/**
 * Walk an env-key map, copy matched values out of `env`, and parse against
 * the schema. Throws a zod error at boot if anything's malformed — much
 * better than a NaN leaking into a setInterval.
 *
 * Tests pass an explicit env object to avoid process-state leakage between
 * cases.
 */
export function loadConfigFromEnv<TSchema extends z.ZodObject<z.ZodRawShape>>(
    schema: TSchema,
    envKeyMap: Record<string, string>,
    env: NodeJS.ProcessEnv = process.env
): z.infer<TSchema> {
    const raw: Record<string, string | undefined> = {}
    for (const [envName, schemaKey] of Object.entries(envKeyMap)) {
        if (env[envName] !== undefined) {
            raw[schemaKey] = env[envName]
        }
    }
    return schema.parse(raw) as z.infer<TSchema>
}
