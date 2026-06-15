import type { Region } from '@/lib/constants'
import {
    getCallbackRedirectUri,
    getClientMapping,
    getRegionSelection,
    putRegionSelection,
    resolveMappingRewrite,
} from '@/lib/kv'
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
        try {
            const json = JSON.parse(body) as Record<string, unknown>
            clientId = (json.client_id as string) || null
            grantType = (json.grant_type as string) || null
        } catch {
            return new Response(
                JSON.stringify({ error: 'invalid_request', error_description: 'Malformed JSON body' }),
                { status: 400, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
            )
        }
    } else {
        const formParams = new URLSearchParams(body)
        clientId = formParams.get('client_id')
        grantType = formParams.get('grant_type')
    }

    const clientIdPrefix = clientId?.slice(0, 8) ?? 'none'

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
            // If we intercepted the authorize callback, rewrite redirect_uri
            // so the regional server sees the proxy callback URL (which the auth code was issued for)
            const storedRedirectUri = await getCallbackRedirectUri(kv, clientId)
            let redirectUriRewrite: { from: string; to: string } | undefined
            if (storedRedirectUri) {
                const proxyCallbackUrl = `${new URL(request.url).origin}/oauth/callback/`
                redirectUriRewrite = { from: storedRedirectUri, to: proxyCallbackUrl }
            }

            console.info(
                JSON.stringify({
                    handler: 'token',
                    grant_type: grantType,
                    client_id_prefix: clientIdPrefix,
                    region_source: 'kv',
                    region,
                })
            )
            const response = await proxyWithMapping(rebuild(), kv, clientId, region, redirectUriRewrite)
            console.info(
                JSON.stringify({
                    handler: 'token',
                    grant_type: grantType,
                    client_id_prefix: clientIdPrefix,
                    region_source: 'kv',
                    region,
                    status: response.status,
                })
            )
            return response
        }
    }

    // For refresh_token grants, try-both is safe (tokens are idempotent to verify).
    // For authorization_code grants without a stored region, return an error
    // rather than leaking the auth code to the wrong server.
    if (grantType === 'authorization_code') {
        console.info(
            JSON.stringify({
                handler: 'token',
                grant_type: grantType,
                client_id_prefix: clientIdPrefix,
                region_source: 'none',
                error: 'no_region_for_auth_code',
            })
        )
        return new Response(
            JSON.stringify({
                error: 'invalid_request',
                error_description: 'Unable to determine region for this authorization code',
            }),
            { status: 400, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
        )
    }

    // If the client was registered through the proxy, we have a permanent mapping
    // of proxy client_id → regional client_ids. Try each region with the correctly
    // rewritten client_id/secret so the regional server recognizes the client.
    // Without this, tryBothRegions sends the proxy (US) client_id to both regions,
    // and EU rejects it because it only knows its own EU client_id.
    if (clientId) {
        const mapping = await getClientMapping(kv, clientId)
        if (mapping) {
            for (const candidateRegion of ['us', 'eu'] as Region[]) {
                const rewrite = resolveMappingRewrite(mapping, candidateRegion)
                if (!rewrite) {
                    continue
                }

                console.info(
                    JSON.stringify({
                        handler: 'token',
                        grant_type: grantType,
                        client_id_prefix: clientIdPrefix,
                        region_source: 'mapping_try_both',
                        candidate_region: candidateRegion,
                    })
                )

                const response = await proxyPostWithClientId(
                    rebuild(),
                    candidateRegion,
                    '/oauth/token/',
                    clientId,
                    rewrite.regionalClientId,
                    undefined,
                    rewrite.clientSecretRewrite
                )

                if (response.ok) {
                    // Re-store the region so subsequent refreshes take the fast path
                    await putRegionSelection(kv, clientId, candidateRegion)

                    console.info(
                        JSON.stringify({
                            handler: 'token',
                            grant_type: grantType,
                            client_id_prefix: clientIdPrefix,
                            region_source: 'mapping_try_both',
                            resolved_region: candidateRegion,
                            status: response.status,
                        })
                    )
                    return response
                }
            }

            console.info(
                JSON.stringify({
                    handler: 'token',
                    grant_type: grantType,
                    client_id_prefix: clientIdPrefix,
                    region_source: 'mapping_try_both',
                    resolved_region: 'none',
                })
            )
            return new Response(
                JSON.stringify({
                    error: 'invalid_request',
                    error_description: 'Unable to determine region',
                }),
                { status: 400, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
            )
        }
    }

    // No mapping — client may have registered directly with a regional server.
    // Try both regions with the raw request.
    console.info(
        JSON.stringify({
            handler: 'token',
            grant_type: grantType,
            client_id_prefix: clientIdPrefix,
            region_source: 'try_both',
        })
    )
    const { response, region } = await tryBothRegions(rebuild(), '/oauth/token/')
    console.info(
        JSON.stringify({
            handler: 'token',
            grant_type: grantType,
            client_id_prefix: clientIdPrefix,
            region_source: 'try_both',
            resolved_region: region,
            status: response.status,
        })
    )
    return response
}

async function proxyWithMapping(
    request: Request,
    kv: KVNamespace,
    proxyClientId: string | null,
    region: Region,
    redirectUriRewrite?: { from: string; to: string }
): Promise<Response> {
    if (proxyClientId) {
        const mapping = await getClientMapping(kv, proxyClientId)
        if (mapping) {
            const rewrite = resolveMappingRewrite(mapping, region)
            if (rewrite) {
                return proxyPostWithClientId(
                    request,
                    region,
                    '/oauth/token/',
                    proxyClientId,
                    rewrite.regionalClientId,
                    redirectUriRewrite,
                    rewrite.clientSecretRewrite
                )
            }
        }
    }

    // No mapping found — proxy directly (client_id may already be regional)
    const { response } = await tryBothRegions(request, '/oauth/token/')
    return response
}
