import { type Region, baseUrlForRegion } from '@/lib/constants'
import { type ClientMapping, getClientMapping, putCallbackRedirectUri, putRegionSelection } from '@/lib/kv'

import REGION_PICKER_HTML from '../static/region-picker.html'

/**
 * OAuth Authorization — region picker + redirect.
 *
 * When the MCP client (or any OAuth client) sends the user to /oauth/authorize/,
 * we show a region picker page. After the user selects their region, we:
 * 1. Store the region selection in KV (for the token exchange step)
 * 2. Translate the proxy client_id to the regional client_id
 * 3. Redirect the user to the correct regional /oauth/authorize/ with all params
 */
export async function handleAuthorize(request: Request, kv: KVNamespace): Promise<Response> {
    const url = new URL(request.url)

    // If region is already selected (via query param from the picker page),
    // redirect to the regional authorize endpoint
    const selectedRegion = url.searchParams.get('_region') as Region | null
    if (selectedRegion === 'us' || selectedRegion === 'eu') {
        return redirectToRegionalAuthorize(url, selectedRegion, kv)
    }

    // Show the region picker page (JS reads query params from window.location.search)
    return new Response(REGION_PICKER_HTML, {
        headers: {
            'Content-Type': 'text/html; charset=utf-8',
            'X-Frame-Options': 'DENY',
            'X-Content-Type-Options': 'nosniff',
            'Referrer-Policy': 'no-referrer',
        },
    })
}

async function redirectToRegionalAuthorize(url: URL, region: Region, kv: KVNamespace): Promise<Response> {
    const clientId = url.searchParams.get('client_id')
    const state = url.searchParams.get('state')
    const originalRedirectUri = url.searchParams.get('redirect_uri')
    let regionalClientId = clientId
    let mapping: ClientMapping | null = null

    // Translate proxy client_id to regional client_id if we have a mapping
    if (clientId) {
        mapping = await getClientMapping(kv, clientId)
        if (mapping) {
            regionalClientId = region === 'eu' ? mapping.eu_client_id : mapping.us_client_id
        }
    }

    // Validate redirect_uri against registered URIs to prevent open redirects.
    // Only enforced for clients registered through the proxy (which have stored redirect_uris).
    if (mapping?.redirect_uris && originalRedirectUri) {
        if (!mapping.redirect_uris.includes(originalRedirectUri)) {
            return new Response(
                JSON.stringify({
                    error: 'invalid_request',
                    error_description: 'redirect_uri is not registered for this client',
                }),
                { status: 400, headers: { 'Content-Type': 'application/json' } }
            )
        }
    }

    // Store region selection keyed by both state and client_id.
    // The token exchange only has client_id (state is not sent to the token endpoint),
    // but we also store by state for the callback interception.
    const kvWrites: Promise<void>[] = []
    if (state) {
        kvWrites.push(putRegionSelection(kv, state, region))
    }
    if (clientId) {
        kvWrites.push(putRegionSelection(kv, clientId, region))
    }

    // Store original redirect_uri and intercept callback only for clients with stored
    // redirect_uris (the proxy callback URL is only in their registered redirect_uris).
    // Legacy clients without redirect_uris fall through to regional server validation.
    if (mapping?.redirect_uris && originalRedirectUri) {
        if (state) {
            kvWrites.push(putCallbackRedirectUri(kv, state, originalRedirectUri))
        }
        if (clientId) {
            kvWrites.push(putCallbackRedirectUri(kv, clientId, originalRedirectUri))
        }
    }

    await Promise.all(kvWrites)

    // Build the regional authorize URL with all original params
    const regionalBase = baseUrlForRegion(region)
    const regionalUrl = new URL('/oauth/authorize/', regionalBase)

    // Replace redirect_uri with proxy's own callback so the client always
    // talks back to the proxy (not directly to the regional server).
    // Only for proxy-registered clients where the proxy callback is a registered URI.
    const proxyCallbackUrl = `${url.protocol}//${url.host}/oauth/callback/`

    // Copy all params except our internal _region param
    for (const [key, value] of url.searchParams.entries()) {
        if (key === '_region') {
            continue
        }
        if (key === 'client_id' && regionalClientId) {
            regionalUrl.searchParams.set(key, regionalClientId)
        } else if (key === 'redirect_uri' && mapping?.redirect_uris) {
            regionalUrl.searchParams.set(key, proxyCallbackUrl)
        } else {
            regionalUrl.searchParams.set(key, value)
        }
    }

    return Response.redirect(regionalUrl.toString(), 302)
}
