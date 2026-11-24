import { type Region, proxyOrigin, regionForBaseUrl } from '@/lib/constants'
import { proxyToRegion } from '@/lib/proxy'
import { rebuildResponse } from '@/lib/token-response'
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
    return proxyToRegion(request, regionParam, EMA_SETUP_PATH)
}

export async function rewriteEmaSetupEndpointInResponse(response: Response, request: Request): Promise<Response> {
    if (!response.ok) {
        return response
    }

    const raw = await response.text()
    const payload = raw.includes('"ema_setup_endpoint"') ? parseObject(raw) : null
    const region = typeof payload?.ema_setup_endpoint === 'string' ? regionOfUrl(payload.ema_setup_endpoint) : null
    if (!payload || !region) {
        return rebuildResponse(response, raw)
    }

    const ema_setup_endpoint = `${proxyOrigin(request)}${EMA_SETUP_PATH}?region=${region}`
    return rebuildResponse(response, JSON.stringify({ ...payload, ema_setup_endpoint }))
}

function parseObject(raw: string): Record<string, unknown> | null {
    try {
        return JSON.parse(raw) as Record<string, unknown>
    } catch {
        return null
    }
}

function regionOfUrl(url: string): Region | null {
    return URL.canParse(url) ? regionForBaseUrl(new URL(url).origin) : null
}
