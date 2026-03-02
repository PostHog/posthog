import { POSTHOG_EU_BASE_URL, POSTHOG_US_BASE_URL, type Region, baseUrlForRegion } from './constants'

/**
 * Proxy a request to a specific region's PostHog server.
 * Rewrites the URL path onto the regional base URL and forwards the request.
 */
export async function proxyToRegion(request: Request, region: Region, path: string): Promise<Response> {
    const baseUrl = baseUrlForRegion(region)
    const url = new URL(path, baseUrl)

    const headers = new Headers(request.headers)
    headers.delete('host')

    return fetch(url.toString(), {
        method: request.method,
        headers,
        body: request.body,
    })
}

/**
 * Proxy a form-encoded or JSON POST body to a region, optionally rewriting the client_id.
 */
export async function proxyPostWithClientId(
    request: Request,
    region: Region,
    path: string,
    proxyClientId: string,
    regionalClientId: string
): Promise<Response> {
    const contentType = request.headers.get('content-type') || ''
    let body: string

    if (contentType.includes('application/json')) {
        const json = await request.json<Record<string, unknown>>()
        if (json.client_id === proxyClientId) {
            json.client_id = regionalClientId
        }
        body = JSON.stringify(json)
    } else {
        // form-urlencoded
        const text = await request.text()
        const params = new URLSearchParams(text)
        if (params.get('client_id') === proxyClientId) {
            params.set('client_id', regionalClientId)
        }
        body = params.toString()
    }

    const baseUrl = baseUrlForRegion(region)
    const url = new URL(path, baseUrl)

    const headers = new Headers(request.headers)
    headers.delete('host')
    // Body was rewritten so the original content-length is wrong
    headers.delete('content-length')

    return fetch(url.toString(), {
        method: 'POST',
        headers,
        body,
    })
}

/**
 * Try a POST request against US first, then EU if US fails.
 * Used for token exchange fallback when region is unknown.
 */
export async function tryBothRegions(request: Request, path: string): Promise<{ response: Response; region: Region }> {
    const body = await request.text()
    const headers = new Headers(request.headers)
    headers.delete('host')

    const usUrl = new URL(path, POSTHOG_US_BASE_URL)
    const usResponse = await fetch(usUrl.toString(), {
        method: 'POST',
        headers,
        body,
    })

    if (usResponse.ok) {
        return { response: usResponse, region: 'us' }
    }

    const euHeaders = new Headers(request.headers)
    euHeaders.delete('host')
    const euUrl = new URL(path, POSTHOG_EU_BASE_URL)
    const euResponse = await fetch(euUrl.toString(), {
        method: 'POST',
        headers: euHeaders,
        body,
    })

    if (euResponse.ok) {
        return { response: euResponse, region: 'eu' }
    }

    return {
        response: new Response(
            JSON.stringify({ error: 'invalid_request', error_description: 'Unable to determine region' }),
            { status: 400, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
        ),
        region: 'us',
    }
}
