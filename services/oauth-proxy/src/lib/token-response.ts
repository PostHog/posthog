import { decodeJwt } from 'jose'

import { type Region, regionForBaseUrl } from './constants'
import { type SigningKeyEnv, reissueIdToken } from './idtoken'

/** Replace the regional ID token in a token response with one this proxy issued. */
export async function reissueIdTokenInResponse(
    response: Response,
    options: { issuer: string; audience: string | null; env: SigningKeyEnv }
): Promise<Response> {
    if (!response.ok) {
        return response
    }

    if (!options.env.OIDC_SIGNING_KEY) {
        // Deploying this worker before the signing key exists must not break token exchanges.
        console.error(JSON.stringify({ handler: 'token', id_token: 'passthrough_no_signing_key' }))
        return response
    }

    const raw = await response.text()
    let payload: Record<string, unknown>
    try {
        payload = JSON.parse(raw) as Record<string, unknown>
    } catch {
        return rebuildResponse(response, raw)
    }

    const idToken = payload.id_token
    if (typeof idToken !== 'string') {
        return rebuildResponse(response, raw)
    }

    const region = regionOfIssuer(idToken)
    if (!region) {
        return serverError('Could not determine which region issued the ID token')
    }

    try {
        const reissued = await reissueIdToken(idToken, {
            region,
            issuer: options.issuer,
            audience: options.audience,
            env: options.env,
        })
        console.info(JSON.stringify({ handler: 'token', id_token: 'reissued', region }))
        return rebuildResponse(response, JSON.stringify({ ...payload, id_token: reissued }))
    } catch (error) {
        // Serving the regional token instead would quietly restore the issuer mismatch.
        console.error(
            JSON.stringify({
                handler: 'token',
                id_token: 'reissue_failed',
                region,
                error: error instanceof Error ? error.message : 'unknown error',
            })
        )
        return serverError('Unable to issue an ID token')
    }
}

/** The unverified claim only selects a key set; the signature is still verified against it. */
function regionOfIssuer(idToken: string): Region | null {
    try {
        return regionForBaseUrl(decodeJwt(idToken).iss ?? '')
    } catch {
        return null
    }
}

function rebuildResponse(response: Response, body: string): Response {
    const headers = new Headers(response.headers)
    // The body was re-serialized, so any upstream length no longer describes it.
    headers.delete('content-length')

    return new Response(body, { status: response.status, statusText: response.statusText, headers })
}

function serverError(description: string): Response {
    return new Response(JSON.stringify({ error: 'server_error', error_description: description }), {
        status: 500,
        headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    })
}
