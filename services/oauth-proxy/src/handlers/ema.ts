import { type Region, proxyOrigin, regionForBaseUrl } from '@/lib/constants'
import { proxyToRegion } from '@/lib/proxy'
import { errorResponse } from '@/lib/validation'

/**
 * Enterprise-managed auth (EMA) setup through `ema_issuer:manage`.
 *
 * A regional server names its own setup endpoint in the token response. A client that reached
 * PostHog through this proxy requires the endpoint on the authorization server's origin, so the
 * token response is rewritten to point here, with the region that minted the token in the query.
 */

export const EMA_SETUP_PATH = '/oauth/ema/trusted-issuer/'

export async function handleEmaTrustedIssuer(request: Request): Promise<Response> {
    const regionParam = new URL(request.url).searchParams.get('region')
    if (regionParam !== 'us' && regionParam !== 'eu') {
        return errorResponse(
            { error: 'invalid_request', error_description: 'Missing or unknown region' },
            { 'Cache-Control': 'no-store' }
        )
    }
    return proxyToRegion(request, regionParam as Region, EMA_SETUP_PATH)
}

export async function rewriteEmaSetupEndpointInResponse(response: Response, request: Request): Promise<Response> {
    if (!response.ok) {
        return response
    }

    const raw = await response.clone().text()
    let payload: Record<string, unknown>
    try {
        payload = JSON.parse(raw) as Record<string, unknown>
    } catch {
        return response
    }

    if (typeof payload.ema_setup_endpoint !== 'string') {
        return response
    }

    let region: Region | null = null
    try {
        region = regionForBaseUrl(new URL(payload.ema_setup_endpoint).origin)
    } catch {
        region = null
    }
    if (!region) {
        return response
    }

    const rewritten = { ...payload, ema_setup_endpoint: `${proxyOrigin(request)}${EMA_SETUP_PATH}?region=${region}` }
    const headers = new Headers(response.headers)
    headers.delete('content-length')
    return new Response(JSON.stringify(rewritten), {
        status: response.status,
        statusText: response.statusText,
        headers,
    })
}
