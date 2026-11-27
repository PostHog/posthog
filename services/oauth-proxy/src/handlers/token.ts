import { rewriteEmaSetupEndpointInResponse } from '@/handlers/ema'
import { type Region, proxyOrigin } from '@/lib/constants'
import { type SigningKeyEnv } from '@/lib/idtoken'
import {
    type ClientMapping,
    getCallbackRedirectUri,
    getClientMapping,
    getCodeRoute,
    getRegionSelection,
    putRegionSelection,
    resolveMappingRewrite,
} from '@/lib/kv'
import { preferClientError, proxyPostWithClientId, tryBothRegions } from '@/lib/proxy'
import { reissueIdTokenInResponse } from '@/lib/token-response'
import { duplicateParamError, errorResponse, findDuplicateParam } from '@/lib/validation'

/** RFC 7523, which PostHog serves as the ID-JAG identity assertion exchange. */
const JWT_BEARER_GRANT_TYPE = 'urn:ietf:params:oauth:grant-type:jwt-bearer'

// The proxy reads a form body with `.get()`, which returns the first value, while Django's
// QueryDict returns the last. A repeat lets the two authenticate different clients.
const SINGLE_VALUE_TOKEN_PARAMS = [
    'client_id',
    'client_secret',
    'grant_type',
    'code',
    'code_verifier',
    'refresh_token',
    'redirect_uri',
] as const

/**
 * OAuth Token Exchange — proxy to the correct region.
 *
 * Routes the token exchange to the correct regional PostHog server.
 * An authorization code is routed by the region recorded for that code when the proxy
 * forwarded its callback. Otherwise the region comes from the KV selection on client_id
 * (stored during the authorize step). That selection is shared by every user of a client,
 * so for refresh_token grants it is only a first guess: a rejection there is retried in the
 * other region. Refreshes with no selection at all fall back to try-both.
 */
export async function handleToken(request: Request, kv: KVNamespace, env: SigningKeyEnv): Promise<Response> {
    const body = await request.text()

    const contentType = request.headers.get('content-type') || ''
    let clientId: string | null = null
    let grantType: string | null = null
    let code: string | null = null

    if (contentType.includes('application/json')) {
        try {
            const json = JSON.parse(body) as Record<string, unknown>
            clientId = (json.client_id as string) || null
            grantType = (json.grant_type as string) || null
            code = typeof json.code === 'string' ? json.code : null
        } catch {
            return errorResponse(
                { error: 'invalid_request', error_description: 'Malformed JSON body' },
                { 'Cache-Control': 'no-store' }
            )
        }
    } else {
        const formParams = new URLSearchParams(body)
        const duplicate = findDuplicateParam(formParams, SINGLE_VALUE_TOKEN_PARAMS)
        if (duplicate) {
            return errorResponse(duplicateParamError(duplicate), { 'Cache-Control': 'no-store' })
        }
        clientId = formParams.get('client_id')
        grantType = formParams.get('grant_type')
        code = formParams.get('code')
    }

    const response = await routeToken(request, kv, body, clientId, grantType, code)

    if (grantType === JWT_BEARER_GRANT_TYPE) {
        // An ID-JAG exchange returns an access token and no ID token, so it has nothing to re-issue.
        return response
    }

    return reissueIdTokenInResponse(response, {
        issuer: proxyOrigin(request),
        audience: clientId,
        permittedUpstreamAudiences: response.ok && clientId ? await permittedUpstreamAudiences(kv, clientId) : [],
        env,
    }).then((reissued) =>
        // Only a code exchange can return an EMA setup token, so refreshes skip the extra body read.
        grantType === 'authorization_code' ? rewriteEmaSetupEndpointInResponse(reissued, request) : reissued
    )
}

/** A client registered through the proxy is known to each region under its own id. */
async function permittedUpstreamAudiences(kv: KVNamespace, clientId: string): Promise<string[]> {
    const mapping = await getClientMapping(kv, clientId)
    if (!mapping) {
        return [clientId]
    }

    return [clientId, mapping.us_client_id, mapping.eu_client_id].filter((id) => Boolean(id))
}

async function routeToken(
    request: Request,
    kv: KVNamespace,
    body: string,
    clientId: string | null,
    grantType: string | null,
    code: string | null
): Promise<Response> {
    const clientIdPrefix = clientId?.slice(0, 8) ?? 'none'

    const rebuild = (): Request =>
        new Request(request.url, {
            method: request.method,
            headers: request.headers,
            body,
        })

    // The regional server checks the assertion's `client_id` claim against the posted one
    // (posthog/api/id_jag.py), so rewriting it to the regional id fails on EU. This grant needs
    // no rewrite: the assertion is the credential and no OAuth application is looked up.
    if (grantType === JWT_BEARER_GRANT_TYPE) {
        const { response, region } = await tryBothRegions(rebuild(), '/oauth/token/')
        console.info(
            JSON.stringify({
                handler: 'token',
                grant_type: grantType,
                client_id_prefix: clientIdPrefix,
                region_source: 'try_both_no_rewrite',
                resolved_region: region,
                status: response.status,
            })
        )
        return response
    }

    if (grantType === 'authorization_code' && code) {
        const route = await getCodeRoute(kv, code)
        // A route is only trusted for the client whose flow recorded it, so a callback replayed
        // with another flow's nonce cannot steer someone else's code to the other region.
        if (route && route.client_id === clientId) {
            const proxyCallbackUrl = `${new URL(request.url).origin}/oauth/callback/`
            const response = await proxyWithMapping(rebuild(), kv, clientId, route.region, {
                from: route.redirect_uri,
                to: proxyCallbackUrl,
            })
            console.info(
                JSON.stringify({
                    handler: 'token',
                    grant_type: grantType,
                    client_id_prefix: clientIdPrefix,
                    region_source: 'code',
                    region: route.region,
                    status: response.status,
                })
            )
            if (response.ok && clientId) {
                await putRegionSelection(kv, clientId, route.region)
            }
            return response
        }
    }

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
            // The selection is shared by every user of this client, so it may name the other user's
            // region. A refresh token is useless to the region that didn't issue it, so retrying a
            // rejected refresh in the other region is safe and recovers from that.
            if (grantType === 'refresh_token') {
                const mapping = await getClientMapping(kv, clientId)
                if (mapping) {
                    const other: Region = region === 'us' ? 'eu' : 'us'
                    return tryMappedRegions(rebuild, kv, clientId, mapping, [region, other], {
                        grantType,
                        clientIdPrefix,
                        source: 'kv_then_other',
                    })
                }
            }

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
            return tryMappedRegions(rebuild, kv, clientId, mapping, ['us', 'eu'], {
                grantType,
                clientIdPrefix,
                source: 'mapping_try_both',
            })
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
    const summary = JSON.stringify({
        handler: 'token',
        grant_type: grantType,
        client_id_prefix: clientIdPrefix,
        region_source: 'try_both',
        resolved_region: region,
        status: response.status,
    })
    if (region) {
        console.info(summary)
    } else {
        console.error(summary)
    }
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

async function tryMappedRegions(
    rebuild: () => Request,
    kv: KVNamespace,
    clientId: string,
    mapping: ClientMapping,
    order: Region[],
    log: { grantType: string | null; clientIdPrefix: string; source: string }
): Promise<Response> {
    const base = {
        handler: 'token',
        grant_type: log.grantType,
        client_id_prefix: log.clientIdPrefix,
        region_source: log.source,
    }
    let bestFailure: Response | null = null

    for (const candidateRegion of order) {
        const rewrite = resolveMappingRewrite(mapping, candidateRegion)
        if (!rewrite) {
            continue
        }

        console.info(JSON.stringify({ ...base, candidate_region: candidateRegion }))

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
            console.info(JSON.stringify({ ...base, resolved_region: candidateRegion, status: response.status }))
            return response
        }

        bestFailure = bestFailure ? preferClientError(bestFailure, response) : response
    }

    if (bestFailure) {
        console.error(JSON.stringify({ ...base, resolved_region: 'none', status: bestFailure.status }))
        return bestFailure
    }

    console.error(JSON.stringify({ ...base, resolved_region: 'none', error: 'no_region_candidates' }))
    return new Response(
        JSON.stringify({
            error: 'invalid_request',
            error_description: 'Unable to determine region',
        }),
        { status: 400, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
    )
}
