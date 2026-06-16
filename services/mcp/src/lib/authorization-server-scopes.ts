import { getAdvertisedOAuthScopes } from '@/tools/toolDefinitions'

// RFC 8414 metadata document, served by the PostHog authorization server (and
// fronted by oauth.posthog.com for cloud). Its `scopes_supported` is the live
// grantable set from the running Django pods — `get_oauth_scopes_supported()`.
const AS_METADATA_PATH = '/.well-known/oauth-authorization-server'

// Refresh fast enough that a scope newly recognised by the AS shows up in our
// advertised list within minutes of the Django deploy completing, slow enough
// that we don't fetch on every metadata request.
const CACHE_TTL_MS = 5 * 60 * 1000

// The metadata route is unauthenticated and hit by clients mid sign-in, so a
// slow AS must never wedge it — bail quickly and fall back to the static list.
const FETCH_TIMEOUT_MS = 1500

interface CacheEntry {
    scopes: Set<string>
    fetchedAt: number
}

// Keyed by authorization-server URL so US and EU (and self-hosted) caches don't
// clobber each other. Module-level: persists across requests in the long-lived
// Node process and within a reused Workers isolate; best-effort either way.
const cache = new Map<string, CacheEntry>()

async function fetchAuthorizationServerScopes(authorizationServerUrl: string): Promise<Set<string> | undefined> {
    const metadataUrl = new URL(AS_METADATA_PATH, authorizationServerUrl).toString()
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
    try {
        const res = await fetch(metadataUrl, {
            signal: controller.signal,
            headers: { Accept: 'application/json' },
        })
        if (!res.ok) {
            return undefined
        }
        const body = (await res.json()) as { scopes_supported?: unknown }
        if (!Array.isArray(body.scopes_supported)) {
            return undefined
        }
        const scopes = body.scopes_supported.filter((scope): scope is string => typeof scope === 'string')
        // An empty list almost certainly means a malformed/partial response, not
        // an AS that genuinely grants nothing — treat it as a miss so we fall
        // back rather than advertise an empty `scopes_supported`.
        return scopes.length > 0 ? new Set(scopes) : undefined
    } catch {
        // Network error, timeout/abort, or non-JSON body — caller falls back.
        return undefined
    } finally {
        clearTimeout(timeout)
    }
}

async function getAuthorizationServerScopes(authorizationServerUrl: string): Promise<Set<string> | undefined> {
    const now = Date.now()
    const cached = cache.get(authorizationServerUrl)
    if (cached && now - cached.fetchedAt < CACHE_TTL_MS) {
        return cached.scopes
    }

    const fetched = await fetchAuthorizationServerScopes(authorizationServerUrl)
    if (fetched) {
        cache.set(authorizationServerUrl, { scopes: fetched, fetchedAt: now })
        return fetched
    }

    // Fetch failed: prefer a stale cache over nothing, else signal "no live data".
    return cached?.scopes
}

/**
 * Scopes to publish as `scopes_supported`, intersected with the scopes the live
 * authorization server actually recognises right now.
 *
 * `getAdvertisedOAuthScopes()` is baked into the MCP image at build time, so a
 * scope added in a single PR reaches the MCP and the Django authorization server
 * through two independently-rolled deploys. If the MCP rolls out first it would
 * advertise a scope the AS doesn't yet know, and spec-compliant clients that
 * trust the advertised list get `invalid_scope` at `/authorize` until Django
 * catches up — which is exactly the deploy-skew outage this guards against.
 *
 * Filtering against the AS's own live `scopes_supported` closes that window: we
 * never advertise a resource scope the running AS can't grant. Identity scopes
 * (no `:`) always ride along. On any fetch failure we fall back to the static
 * list, so the worst case is the previous behaviour, never worse.
 */
export async function getLiveAdvertisedOAuthScopes(authorizationServerUrl: string): Promise<readonly string[]> {
    const advertised = getAdvertisedOAuthScopes()
    const live = await getAuthorizationServerScopes(authorizationServerUrl)
    if (!live) {
        return advertised
    }
    return advertised.filter((scope) => !scope.includes(':') || live.has(scope))
}

/** Test-only: drop the cached AS scopes so cases don't bleed into each other. */
export function resetAuthorizationServerScopesCacheForTests(): void {
    cache.clear()
}
