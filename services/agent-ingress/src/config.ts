import { z } from 'zod'

const ConfigSchema = z.object({
    port: z.coerce.number().int().min(1).max(65_535).default(3030),
    /** agent-runtime queue DB (where session jobs live). */
    queueDbUrl: z.string().min(1),
    /** Main posthog Postgres — read agent_stack_agentapplication / *revision directly. */
    posthogDbUrl: z.string().min(1),
    /** ioredis URL. When unset, we fall back to the in-memory bus (single-process only). */
    redisUrl: z.string().optional(),
    /** Resolver cache TTL for `(domain → revision)` entries. */
    resolverTtlMs: z.coerce.number().int().min(0).default(5_000),
    /** Suffix for application subdomains, e.g. ".agents.posthog.com". */
    domainSuffix: z.string().default('.agents.posthog.com'),
})

export type IngressConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): IngressConfig {
    return ConfigSchema.parse({
        port: env.PORT,
        queueDbUrl: env.AGENT_RUNTIME_QUEUE_DATABASE_URL,
        posthogDbUrl: env.POSTHOG_DATABASE_URL,
        redisUrl: env.REDIS_URL,
        resolverTtlMs: env.RESOLVER_TTL_MS,
        domainSuffix: env.DOMAIN_SUFFIX,
    })
}
