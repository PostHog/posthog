import { POSTHOG_EU_BASE_URL, POSTHOG_US_BASE_URL, type Region } from '@/lib/constants'
import { type SigningKeyEnv, proxyJwks } from '@/lib/idtoken'
import { getClientMapping, getRegionSelection } from '@/lib/kv'
import { proxyPostWithClientId, proxyToRegion, tryBothRegions } from '@/lib/proxy'
import { errorResponse } from '@/lib/validation'

/**
 * Passthrough handlers for OAuth endpoints that simply need to reach the correct region.
 */

// Every relying party fetches this on its first ID token verification. Signing keys rotate in months.
const JWKS_CACHE_TTL_MS = 600 * 1000

let cachedJwks: { body: string; cachedUntil: number } | null = null

/**
 * Revoke token — route to the correct region based on client_id, fallback to try-both.
 */
export async function handleRevoke(request: Request, kv: KVNamespace): Promise<Response> {
    return routeByClientId(request, kv, '/oauth/revoke/')
}

/**
 * Introspect token — try US first, then EU.
 * Unlike tryBothRegions, we check the response body: introspect returns
 * 200 {"active": false} for unknown tokens, so HTTP status alone isn't enough.
 */
export async function handleIntrospect(request: Request): Promise<Response> {
    const body = await request.text()
    const headers = new Headers(request.headers)
    headers.delete('host')
    headers.delete('content-length')

    const usResponse = await fetch(new URL('/oauth/introspect/', POSTHOG_US_BASE_URL).toString(), {
        method: 'POST',
        headers,
        body,
    })

    if (usResponse.ok) {
        const usData = await usResponse.json<Record<string, unknown>>()
        if (usData.active === true) {
            return new Response(JSON.stringify(usData), {
                status: 200,
                headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
            })
        }
    }

    const euHeaders = new Headers(request.headers)
    euHeaders.delete('host')
    euHeaders.delete('content-length')

    const euResponse = await fetch(new URL('/oauth/introspect/', POSTHOG_EU_BASE_URL).toString(), {
        method: 'POST',
        headers: euHeaders,
        body,
    })

    return euResponse
}

/**
 * UserInfo — try both regions with the Bearer token.
 */
export async function handleUserInfo(request: Request): Promise<Response> {
    const { response } = await tryBothRegions(request, '/oauth/userinfo/')
    return response
}

/**
 * JWKS — this proxy's signing keys, plus the regional ones.
 *
 * The regional keys stay published because the regional servers also sign the ID-JAG access
 * tokens (`at+jwt`) clients receive through this proxy. Key ids differ, so a verifier selects
 * the right key on its own.
 */
export async function handleJwks(request: Request, _kv: KVNamespace, env: SigningKeyEnv): Promise<Response> {
    const cached = cachedJwks && cachedJwks.cachedUntil > Date.now() ? cachedJwks.body : null
    if (cached) {
        return jwksResponse(cached)
    }

    const [proxyKeys, ...regional] = await Promise.all([
        proxyJwks(env),
        regionalKeys(request, 'us'),
        regionalKeys(request, 'eu'),
    ])

    const keys = [...proxyKeys, ...regional.flat()]
    if (keys.length === proxyKeys.length) {
        return new Response(JSON.stringify({ error: 'server_error' }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        })
    }

    const body = JSON.stringify({ keys: dedupeByKid(keys) })
    cachedJwks = { body, cachedUntil: Date.now() + JWKS_CACHE_TTL_MS }

    return jwksResponse(body)
}

/** A region that is unreachable contributes nothing rather than failing the whole document. */
async function regionalKeys(request: Request, region: Region): Promise<unknown[]> {
    try {
        const response = await proxyToRegion(request, region, '/.well-known/jwks.json')
        if (!response.ok) {
            return []
        }
        const body = (await response.json()) as { keys?: unknown[] }
        return body.keys ?? []
    } catch {
        return []
    }
}

function dedupeByKid(keys: unknown[]): unknown[] {
    const seen = new Set<string>()
    return keys.filter((key) => {
        const kid = (key as { kid?: string }).kid
        if (!kid || seen.has(kid)) {
            return !kid
        }
        seen.add(kid)
        return true
    })
}

function jwksResponse(body: string): Response {
    return new Response(body, {
        headers: {
            'Content-Type': 'application/json',
            'Cache-Control': `public, max-age=${JWKS_CACHE_TTL_MS / 1000}`,
            'Access-Control-Allow-Origin': '*',
        },
    })
}

async function routeByClientId(request: Request, kv: KVNamespace, path: string): Promise<Response> {
    const body = await request.text()

    const contentType = request.headers.get('content-type') || ''
    let clientId: string | null = null

    if (contentType.includes('application/json')) {
        try {
            const json = JSON.parse(body) as Record<string, unknown>
            clientId = (json.client_id as string) || null
        } catch {
            return errorResponse({ error: 'invalid_request', error_description: 'Malformed JSON body' })
        }
    } else {
        const params = new URLSearchParams(body)
        clientId = params.get('client_id')
    }

    const rebuild = (): Request =>
        new Request(request.url, {
            method: request.method,
            headers: request.headers,
            body,
        })

    if (clientId) {
        const region = await getRegionSelection(kv, clientId)
        if (region) {
            const mapping = await getClientMapping(kv, clientId)
            if (mapping) {
                const regionalClientId = region === 'eu' ? mapping.eu_client_id : mapping.us_client_id
                if (regionalClientId) {
                    return proxyPostWithClientId(rebuild(), region, path, clientId, regionalClientId)
                }
            }
        }
    }

    const { response } = await tryBothRegions(rebuild(), path)
    return response
}
