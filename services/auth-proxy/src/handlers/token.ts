import type { Region } from '@/lib/constants'
import { getClientMapping, getRegionSelection } from '@/lib/kv'
import { proxyPostWithClientId, tryBothRegions } from '@/lib/proxy'

/**
 * OAuth Token Exchange — proxy to the correct region.
 *
 * Routes the token exchange to the correct regional PostHog server.
 * Region is determined by KV lookup on client_id (stored during the authorize step).
 * For refresh_token grants, we fall back to try-both since the client may not
 * have gone through our authorize flow.
 */
export async function handleToken(request: Request, kv: KVNamespace): Promise<Response> {
    const body = await request.text()

    const contentType = request.headers.get('content-type') || ''
    let clientId: string | null = null
    let grantType: string | null = null

    if (contentType.includes('application/json')) {
        const json = JSON.parse(body) as Record<string, unknown>
        clientId = (json.client_id as string) || null
        grantType = (json.grant_type as string) || null
    } else {
        const formParams = new URLSearchParams(body)
        clientId = formParams.get('client_id')
        grantType = formParams.get('grant_type')
    }

    const rebuild = (): Request =>
        new Request(request.url, {
            method: request.method,
            headers: request.headers,
            body,
        })

    // Look up region by client_id (stored during the authorize step)
    if (clientId) {
        const region = await getRegionSelection(kv, clientId)
        if (region) {
            return proxyWithMapping(rebuild(), kv, clientId, region)
        }
    }

    // For refresh_token grants, try-both is safe (tokens are idempotent to verify).
    // For authorization_code grants without a stored region, return an error
    // rather than leaking the auth code to the wrong server.
    if (grantType === 'authorization_code') {
        return new Response(
            JSON.stringify({
                error: 'invalid_request',
                error_description: 'Unable to determine region for this authorization code',
            }),
            { status: 400, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
        )
    }

    const { response } = await tryBothRegions(rebuild(), '/oauth/token/')
    return response
}

async function proxyWithMapping(
    request: Request,
    kv: KVNamespace,
    proxyClientId: string | null,
    region: Region
): Promise<Response> {
    if (proxyClientId) {
        const mapping = await getClientMapping(kv, proxyClientId)
        if (mapping) {
            const regionalClientId = region === 'eu' ? mapping.eu_client_id : mapping.us_client_id
            if (regionalClientId) {
                return proxyPostWithClientId(request, region, '/oauth/token/', proxyClientId, regionalClientId)
            }
        }
    }

    // No mapping found — proxy directly (client_id may already be regional)
    const { response } = await tryBothRegions(request, '/oauth/token/')
    return response
}
