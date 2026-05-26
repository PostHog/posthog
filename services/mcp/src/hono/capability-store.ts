/**
 * Per-token cache of the client's `initialize` capabilities.
 *
 * The Hono MCP server is stateless per-request: `tools/call` runs without
 * direct access to the original `initialize` it implicitly continued. The
 * MCP spec, however, requires the server NOT to send a server-initiated
 * request the client never advertised support for (`elicitation/create`
 * being the load-bearing example today).
 *
 * Solving this without a session table: we cache the relevant slice of
 * `capabilities` from each `initialize`, keyed by the auth `userHash`, in
 * Redis with a long TTL. Subsequent requests do one fast `GET` to decide
 * whether to wire `Context.elicit` for the tool handler. A cache miss
 * (cold pod, never-initialized client, evicted entry) is treated as
 * fail-closed — see `dispatchToolsCallWithMaybeSse`.
 *
 * The stored shape is intentionally narrow. We don't snapshot the whole
 * `capabilities` object — only what the dispatcher needs to gate behavior.
 * Adding a new capability flag is a deliberate decision (extend the type,
 * extend the writer, extend a reader).
 */

import type { RedisLike } from './cache/RedisCache'
import { clientCapabilityCacheTotal } from './metrics'

const KEY_PREFIX = 'mcp:client-caps'

/**
 * Cache TTL. Initialize is observed often enough in practice that 24h is
 * generous; the cache exists primarily to bridge across requests within the
 * same logical session, not across days. Long TTL keeps the GET hit rate
 * high without forcing clients to re-initialize for every tool call.
 */
const DEFAULT_TTL_SECONDS = 24 * 60 * 60

/**
 * Narrow projection of `InitializeRequest.params.capabilities` retained
 * for dispatcher decisions. Today only `elicitation` matters. The MCP
 * draft spec uses an empty object `{}` to denote form-mode-only support;
 * `{ form: {} }` and `{ url: {} }` declare specific modes.
 */
export interface CachedClientCapabilities {
    elicitation?: {
        form?: Record<string, never>
        url?: Record<string, never>
    }
}

export interface CapabilityStoreOptions {
    /** Override the TTL (seconds). Defaults to 24h. */
    ttlSeconds?: number
}

export class CapabilityStore {
    private readonly ttlSeconds: number

    constructor(
        private readonly redis: RedisLike,
        options: CapabilityStoreOptions = {}
    ) {
        this.ttlSeconds = options.ttlSeconds ?? DEFAULT_TTL_SECONDS
    }

    async get(userHash: string): Promise<CachedClientCapabilities | undefined> {
        const key = buildKey(userHash)
        let raw: string | null
        try {
            raw = await this.redis.get(key)
        } catch {
            // A Redis blip on capability read should not fail the request.
            // Surface as a miss; the dispatcher's fail-closed default keeps
            // us safe.
            clientCapabilityCacheTotal.inc({ result: 'miss' })
            return undefined
        }
        if (raw === null) {
            clientCapabilityCacheTotal.inc({ result: 'miss' })
            return undefined
        }
        try {
            const parsed = JSON.parse(raw) as CachedClientCapabilities
            clientCapabilityCacheTotal.inc({ result: 'hit' })
            return parsed
        } catch {
            // Treat corrupt JSON as stale rather than crash. A subsequent
            // initialize will overwrite the key.
            clientCapabilityCacheTotal.inc({ result: 'stale' })
            return undefined
        }
    }

    async set(userHash: string, capabilities: CachedClientCapabilities): Promise<void> {
        const key = buildKey(userHash)
        try {
            await this.redis.set(key, JSON.stringify(capabilities), 'EX', this.ttlSeconds)
        } catch {
            // Best-effort write — a failed set just means the next request
            // will pay one extra fail-closed bounce. Don't break initialize.
        }
    }
}

function buildKey(userHash: string): string {
    return `${KEY_PREFIX}:${userHash}`
}

/**
 * Project an incoming `initialize` `capabilities` object down to the
 * narrow cached shape. ALWAYS returns a value (even an empty `{}`) so the
 * caller can overwrite stale cache entries — a client re-initializing with
 * fewer capabilities than a prior session must not inherit the prior state.
 *
 * Returns `{}` (no `elicitation` key) when the client declared no
 * elicitation support; the dispatcher reads this as "no capability".
 */
export function projectClientCapabilities(raw: unknown): CachedClientCapabilities {
    if (raw === null || typeof raw !== 'object') {
        return {}
    }
    const obj = raw as Record<string, unknown>
    const elicitation = obj['elicitation']
    if (elicitation === undefined || typeof elicitation !== 'object' || elicitation === null) {
        return {}
    }
    const elicitObj = elicitation as Record<string, unknown>
    const out: CachedClientCapabilities['elicitation'] = {}
    if ('form' in elicitObj && typeof elicitObj['form'] === 'object' && elicitObj['form'] !== null) {
        out.form = {}
    }
    if ('url' in elicitObj && typeof elicitObj['url'] === 'object' && elicitObj['url'] !== null) {
        out.url = {}
    }
    // An empty `elicitation: {}` per the spec means "form-mode only".
    // Preserve that semantic.
    return { elicitation: out }
}

/**
 * Does the cached capability declare any form of elicitation support?
 * Both `elicitation: {}` (spec-defined form-only) and any of the
 * explicit-mode shapes count.
 */
export function supportsAnyElicitation(caps: CachedClientCapabilities | undefined): boolean {
    return caps?.elicitation !== undefined
}
