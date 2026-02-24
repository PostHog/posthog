import { type Region, baseUrlForRegion } from '@/lib/constants'
import { getClientMapping, putRegionSelection } from '@/lib/kv'

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
    let regionalClientId = clientId

    // Translate proxy client_id to regional client_id if we have a mapping
    if (clientId) {
        const mapping = await getClientMapping(kv, clientId)
        if (mapping) {
            regionalClientId = region === 'eu' ? mapping.eu_client_id : mapping.us_client_id
        }
    }

    // Store region selection keyed by the OAuth state param (unique per session)
    // to avoid concurrent users overwriting each other's region choice
    if (state) {
        await putRegionSelection(kv, state, region)
    } else if (clientId) {
        await putRegionSelection(kv, clientId, region)
    }

    // Build the regional authorize URL with all original params
    const regionalBase = baseUrlForRegion(region)
    const regionalUrl = new URL('/oauth/authorize/', regionalBase)

    // Copy all params except our internal _region param
    for (const [key, value] of url.searchParams.entries()) {
        if (key === '_region') {
            continue
        }
        if (key === 'client_id' && regionalClientId) {
            regionalUrl.searchParams.set(key, regionalClientId)
        } else {
            regionalUrl.searchParams.set(key, value)
        }
    }

    return Response.redirect(regionalUrl.toString(), 302)
}
