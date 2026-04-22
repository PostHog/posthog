import { env as workerEnv } from 'cloudflare:workers'

export interface LocalFlagGroup {
    rollout_percentage?: number | null
    properties?: Array<{ type?: string; key?: string; value?: unknown; operator?: string }>
    variant?: string | null
}

export interface LocalFlagMultivariate {
    variants?: Array<{ key: string; rollout_percentage?: number }>
}

export interface LocalFlagFilters {
    groups?: LocalFlagGroup[]
    multivariate?: LocalFlagMultivariate | null
    aggregation_group_type_index?: number | null
}

export interface LocalFlagDefinition {
    key: string
    active: boolean
    deleted?: boolean
    filters?: LocalFlagFilters
    ensure_experience_continuity?: boolean
    has_encrypted_payloads?: boolean
}

export interface FlagDefinitionsSnapshot {
    etag: string | null
    fetchedAt: number
    flags: LocalFlagDefinition[]
    groupTypeMapping?: Record<string, string>
}

export const FLAG_DEFS_KV_KEY = 'flag-defs:v1'
const LOGICAL_TTL_MS = 5 * 60 * 1000
const HARD_TTL_SECONDS = 60 * 60 // 1h KV expirationTtl
const EDGE_CACHE_TTL_SECONDS = 60
const MAX_PAYLOAD_BYTES = 20 * 1024 * 1024
const WARN_PAYLOAD_BYTES = 1 * 1024 * 1024

type WaitUntil = { waitUntil: (p: Promise<unknown>) => void }

function log(reason: string, extra: Record<string, unknown> = {}): void {
    console.info('[flag-cache]', JSON.stringify({ reason, ...extra }))
}

function isFresh(snapshot: FlagDefinitionsSnapshot): boolean {
    return Date.now() - snapshot.fetchedAt < LOGICAL_TTL_MS
}

/**
 * Read the flag-definitions snapshot from KV, refreshing in the background
 * (or synchronously on miss). Returns `null` if no snapshot is available —
 * caller should fall back to remote evaluation.
 */
export async function getFlagDefinitions(env: Env, ctx?: WaitUntil): Promise<FlagDefinitionsSnapshot | null> {
    if (!env.FLAG_DEFS_KV) {
        return null
    }

    let snapshot: FlagDefinitionsSnapshot | null = null
    try {
        snapshot = await env.FLAG_DEFS_KV.get<FlagDefinitionsSnapshot>(FLAG_DEFS_KV_KEY, {
            type: 'json',
            cacheTtl: EDGE_CACHE_TTL_SECONDS,
        })
    } catch (error) {
        log('kv_read_error', { error: error instanceof Error ? error.message : String(error) })
    }

    if (snapshot && isFresh(snapshot)) {
        return snapshot
    }

    if (snapshot) {
        // Stale-while-revalidate: return stale immediately, refresh in background.
        if (ctx) {
            ctx.waitUntil(refreshFlagDefinitions(env).catch((e) => log('bg_refresh_failed', { error: String(e) })))
        }
        return snapshot
    }

    // Hard miss: fetch synchronously. Worst case, one DO in the world pays this cost.
    try {
        return await refreshFlagDefinitions(env)
    } catch (error) {
        log('miss_refresh_failed', { error: error instanceof Error ? error.message : String(error) })
        return null
    }
}

/**
 * Fetch the latest flag definitions from PostHog and persist to KV.
 * Preserves flag bodies on 304 (just bumps fetchedAt).
 * Returns the new snapshot, or the prior one on upstream failure.
 */
export async function refreshFlagDefinitions(env: Env): Promise<FlagDefinitionsSnapshot | null> {
    if (!env.FLAG_DEFS_KV || !env.MCP_FLAG_LOCAL_EVAL_KEY) {
        return null
    }

    const host = env.POSTHOG_ANALYTICS_HOST
    if (!host) {
        return null
    }

    const url = `${host.replace(/\/$/, '')}/api/feature_flag/local_evaluation/?send_cohorts=false`

    let prior: FlagDefinitionsSnapshot | null = null
    try {
        prior = await env.FLAG_DEFS_KV.get<FlagDefinitionsSnapshot>(FLAG_DEFS_KV_KEY, { type: 'json' })
    } catch {
        prior = null
    }

    const headers: Record<string, string> = {
        Authorization: `Bearer ${env.MCP_FLAG_LOCAL_EVAL_KEY}`,
        'User-Agent': 'posthog-mcp flag-cache',
    }
    if (prior?.etag) {
        headers['If-None-Match'] = prior.etag
    }

    let response: Response
    try {
        response = await fetch(url, { method: 'GET', headers })
    } catch (error) {
        log('fetch_error', { error: error instanceof Error ? error.message : String(error) })
        return prior
    }

    if (response.status === 304 && prior) {
        const bumped: FlagDefinitionsSnapshot = { ...prior, fetchedAt: Date.now() }
        await writeSnapshot(env, bumped)
        return bumped
    }

    if (!response.ok) {
        log('upstream_not_ok', { status: response.status })
        if (response.status === 401 || response.status === 403) {
            // Auth misconfig — surface once, let caller fall back.
            log('auth_error', { status: response.status })
        }
        return prior
    }

    const rawText = await response.text()
    const byteLength = new TextEncoder().encode(rawText).byteLength

    if (byteLength > MAX_PAYLOAD_BYTES) {
        log('payload_too_large', { bytes: byteLength, max: MAX_PAYLOAD_BYTES })
        return prior
    }
    if (byteLength > WARN_PAYLOAD_BYTES) {
        log('payload_large_warning', { bytes: byteLength })
    }

    let parsed: { flags?: LocalFlagDefinition[]; group_type_mapping?: Record<string, string> }
    try {
        parsed = JSON.parse(rawText)
    } catch (error) {
        log('parse_error', { error: error instanceof Error ? error.message : String(error) })
        return prior
    }

    const snapshot: FlagDefinitionsSnapshot = {
        etag: response.headers.get('etag'),
        fetchedAt: Date.now(),
        flags: Array.isArray(parsed.flags) ? parsed.flags : [],
        ...(parsed.group_type_mapping ? { groupTypeMapping: parsed.group_type_mapping } : {}),
    }

    await writeSnapshot(env, snapshot)
    return snapshot
}

async function writeSnapshot(env: Env, snapshot: FlagDefinitionsSnapshot): Promise<void> {
    try {
        await env.FLAG_DEFS_KV.put(FLAG_DEFS_KV_KEY, JSON.stringify(snapshot), {
            expirationTtl: HARD_TTL_SECONDS,
        })
    } catch (error) {
        log('kv_write_error', { error: error instanceof Error ? error.message : String(error) })
    }
}

/**
 * Local-only check whether the cache-backed path is configured.
 * Callers should skip the KV path when this is false.
 */
export function isLocalEvalEnabled(env?: Env): boolean {
    const e = env ?? (workerEnv as Env)
    return e?.MCP_LOCAL_EVAL_ENABLED === '1' && !!e?.FLAG_DEFS_KV && !!e?.MCP_FLAG_LOCAL_EVAL_KEY
}
