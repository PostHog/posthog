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
 * Introspect token — try both regions since the token could be from either.
 */
export async function handleIntrospect(request: Request): Promise<Response> {
    const { response } = await tryBothRegions(request, '/oauth/introspect/')
    return response
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
