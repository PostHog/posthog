import { POSTHOG_EU_BASE_URL, POSTHOG_US_BASE_URL } from '@/lib/constants'
import { getClientMapping, getRegionSelection } from '@/lib/kv'
import { proxyPostWithClientId, proxyToRegion, tryBothRegions } from '@/lib/proxy'

/**
 * Passthrough handlers for OAuth endpoints that simply need to reach the correct region.
 */

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
 * JWKS — proxy to US (keys should be the same across regions).
 */
export async function handleJwks(request: Request): Promise<Response> {
    return proxyToRegion(request, 'us', '/.well-known/jwks.json')
}

async function routeByClientId(request: Request, kv: KVNamespace, path: string): Promise<Response> {
    const body = await request.text()

    const contentType = request.headers.get('content-type') || ''
    let clientId: string | null = null

    if (contentType.includes('application/json')) {
        const json = JSON.parse(body) as Record<string, unknown>
        clientId = (json.client_id as string) || null
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
