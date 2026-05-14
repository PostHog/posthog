import { z } from 'zod'

export type RoutingMode = 'domain' | 'path'

const ConfigSchema = z.object({
    port: z.coerce.number().int().min(1).max(65_535).default(3030),
    /** agent-runtime queue DB (where session jobs live). */
    queueDbUrl: z.string().min(1),
    /** Main posthog Postgres — read agent_stack_agentapplication / *revision directly. */
    posthogDbUrl: z.string().min(1),
    /** ioredis URL. When unset, we fall back to the in-memory bus (single-process only). */
    redisUrl: z.string().optional(),
    /**
     * Same comma-separated key list Django uses for `EncryptedTextField`.
     * Slack triggers (and any future trigger with secret-bound fields) read
     * the agent's encrypted_env at request time and decrypt in-process.
     * Default matches Django's local-dev fallback (`posthog/settings/access.py`)
     * so a fresh hogli stack boots without extra env-var plumbing.
     */
    encryptionSaltKeys: z.string().default('00beef0000beef0000beef0000beef00'),
    /** Resolver cache TTL for `(domain → revision)` entries. */
    resolverTtlMs: z.coerce.number().int().min(0).default(5_000),
    /**
     * How tenant identification works on inbound requests:
     *   - `domain` (production default — anywhere `SITE_URL` points at a real
     *     public hostname): pull the slug from the Host header
     *     (`<slug>.agents.<site_host>`) and resolve by domain.
     *   - `path` (local-dev default — `SITE_URL` unset or pointing at
     *     localhost/IP): pull the slug from a `/agents/<slug>/...` URL prefix
     *     and resolve by slug. Convenient when a wildcard subdomain isn't
     *     available (Cloudflare Quick Tunnels, ngrok free, etc).
     *
     * Explicit `ROUTING_MODE` env always wins; the default is derived from
     * `SITE_URL` in `loadConfig`.
     */
    routingMode: z.enum(['domain', 'path']).default('path'),
    /**
     * Suffix for application subdomains in `domain` mode. Defaults derive from
     * `SITE_URL` (e.g. `https://us.posthog.com` → `.agents.us.posthog.com`,
     * `https://eu.posthog.com` → `.agents.eu.posthog.com`). Explicit
     * `DOMAIN_SUFFIX` env always wins. Falls back to `.agents.posthog.com`
     * when neither is set.
     */
    domainSuffix: z.string().default('.agents.posthog.com'),
})

export type IngressConfig = z.infer<typeof ConfigSchema>

export function loadConfig(env: NodeJS.ProcessEnv = process.env): IngressConfig {
    return ConfigSchema.parse({
        port: env.PORT,
        queueDbUrl: env.AGENT_RUNTIME_QUEUE_DATABASE_URL,
        posthogDbUrl: env.POSTHOG_DATABASE_URL,
        redisUrl: env.REDIS_URL,
        encryptionSaltKeys: env.ENCRYPTION_SALT_KEYS,
        resolverTtlMs: env.RESOLVER_TTL_MS,
        routingMode: env.ROUTING_MODE ?? deriveRoutingMode(env.SITE_URL),
        domainSuffix: env.DOMAIN_SUFFIX ?? deriveDomainSuffix(env.SITE_URL),
    })
}

/**
 * Default routing mode based on `SITE_URL` shape. Dev stacks (no SITE_URL, or
 * SITE_URL → localhost / IP) can't get a wildcard subdomain without extra
 * config, so they default to path-mode. Production deployments always set
 * `SITE_URL` to their canonical hostname → they default to domain-mode.
 *
 * Returning `undefined` lets the schema's `.default('domain')` kick in for the
 * "we genuinely don't know" middle ground — safer to require an explicit
 * `ROUTING_MODE=path` than to accidentally weaken prod routing.
 */
function deriveRoutingMode(siteUrl: string | undefined): 'domain' | 'path' | undefined {
    if (!siteUrl) {
        return 'path'
    }
    let host: string
    try {
        host = new URL(siteUrl).hostname.toLowerCase()
    } catch {
        return 'path'
    }
    if (!host || host === 'localhost' || /^[\d.]+$/.test(host) || /^[\da-f:]+$/i.test(host)) {
        return 'path'
    }
    return 'domain'
}

/**
 * Derive a sensible default domain suffix from PostHog's main `SITE_URL`.
 * Keeps the regional clusters honest (US → `.agents.us.posthog.com`,
 * EU → `.agents.eu.posthog.com`, self-hosted → `.agents.<their host>`).
 * Localhost / explicit IPs / unparseable values return `undefined` so the
 * schema default (`.agents.posthog.com`) kicks in — and the deployer is
 * expected to set `DOMAIN_SUFFIX` explicitly there anyway.
 */
function deriveDomainSuffix(siteUrl: string | undefined): string | undefined {
    if (!siteUrl) {
        return undefined
    }
    let host: string
    try {
        host = new URL(siteUrl).hostname.toLowerCase()
    } catch {
        return undefined
    }
    if (!host || host === 'localhost' || /^[\d.]+$/.test(host) || /^[\da-f:]+$/i.test(host)) {
        return undefined
    }
    return `.agents.${host}`
}
