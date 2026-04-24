import type { FlagDefinitionCacheData, FlagDefinitionCacheProvider } from 'posthog-node/experimental'

// Base KV-backed flag-definition cache. Mirrors the pattern from
// posthog-js/examples/example-cloudflare-kv-cache — subclasses specialize
// read-only (request path) vs. write-only (scheduled cron) behavior.
class CloudflareKVFlagCache implements FlagDefinitionCacheProvider {
    private static readonly CACHE_KEY_PREFIX = 'posthog:flags:'

    constructor(
        protected kv: KVNamespace,
        protected teamKey: string
    ) {}

    protected get cacheKey(): string {
        return `${CloudflareKVFlagCache.CACHE_KEY_PREFIX}${this.teamKey}`
    }

    async getFlagDefinitions(): Promise<FlagDefinitionCacheData | undefined> {
        try {
            // cacheTtl keeps hot isolates at ~0ms after the first KV read in a colo.
            const cached = await this.kv.get(this.cacheKey, { cacheTtl: 60 * 5 })
            if (cached === null) {
                return undefined
            }
            return JSON.parse(cached) as FlagDefinitionCacheData
        } catch {
            return undefined
        }
    }

    shouldFetchFlagDefinitions(): boolean {
        return false
    }

    async onFlagDefinitionsReceived(data: FlagDefinitionCacheData): Promise<void> {
        await this.kv.put(this.cacheKey, JSON.stringify(data))
    }

    shutdown(): void {
        // no-op
    }
}

// Used by request handlers — never fetches, never writes.
export class CloudflareKVFlagCacheReader extends CloudflareKVFlagCache {
    override shouldFetchFlagDefinitions(): boolean {
        return false
    }

    override async onFlagDefinitionsReceived(): Promise<void> {
        // Should not be called — `shouldFetchFlagDefinitions` returns false.
        throw new Error('CloudflareKVFlagCacheReader is read-only and cannot store flag definitions.')
    }
}

// Used by the scheduled cron — always fetches fresh definitions and overwrites cache.
export class CloudflareKVFlagCacheWriter extends CloudflareKVFlagCache {
    override getFlagDefinitions(): Promise<FlagDefinitionCacheData | undefined> {
        // Force a fresh fetch from PostHog on every invocation.
        return Promise.resolve(undefined)
    }

    override shouldFetchFlagDefinitions(): boolean {
        return true
    }
}

export function isLocalEvalConfigured(env: Env): boolean {
    return !!env.MCP_KV && !!env.MCP_FLAG_LOCAL_EVAL_KEY && !!env.POSTHOG_ANALYTICS_API_KEY
}

export function isLocalEvalEnabled(env: Env): boolean {
    return env.MCP_LOCAL_EVAL_ENABLED === '1' && isLocalEvalConfigured(env)
}
