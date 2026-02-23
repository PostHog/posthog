import type { Region } from '@/lib/constants'
import { getClientMapping, getRegionSelection } from '@/lib/kv'
import { proxyPostWithClientId, tryBothRegions } from '@/lib/proxy'

/**
 * OAuth Token Exchange — proxy to the correct region.
 *
 * Routes the token exchange (authorization_code or refresh_token) to the correct
 * regional PostHog server. Region is determined by:
 * 1. KV lookup from the authorize step (stored when user picked their region)
 * 2. Fallback: try US, then EU (auth codes are only valid at the issuing server)
 */
export async function handleToken(request: Request, kv: KVNamespace): Promise<Response> {
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

    // Try to determine region from KV (set during the authorize step)
    if (clientId) {
        const region = await getRegionSelection(kv, clientId)
        if (region) {
            return proxyWithMapping(rebuild(), kv, clientId, region)
        }
    }

    // Fallback: try both regions. The auth code is only valid at the server that
    // issued it, so the wrong server returns invalid_grant without consuming it.
    const { response } = await tryBothRegions(rebuild(), '/oauth/token/')
    return response
}

async function proxyWithMapping(
    request: Request,
    kv: KVNamespace,
    proxyClientId: string,
    region: Region
): Promise<Response> {
    const mapping = await getClientMapping(kv, proxyClientId)

    if (mapping) {
        const regionalClientId = region === 'eu' ? mapping.eu_client_id : mapping.us_client_id
        if (regionalClientId) {
            return proxyPostWithClientId(request, region, '/oauth/token/', proxyClientId, regionalClientId)
        }
    }

    // No mapping found — proxy directly (client_id may already be regional)
    const { response } = await tryBothRegions(request, '/oauth/token/')
    return response
}
