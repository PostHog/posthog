/**
 * The session-bound inference-proxy capability token (agent-sandbox-tiers.md
 * §8). The tier-2 coding sandbox calls the model through the ingress
 * inference proxy, never the ai-gateway directly — so the only "credential"
 * inside the sandbox is this token: an audience-bound internal JWT carrying
 * `{session_id, exp}`, worthless anywhere except the proxy, and dead the
 * moment the session stops being live. The real gateway key stays on the
 * proxy side.
 *
 * The runner mints one per sandbox acquisition; the ingress proxy verifies
 * statelessly (shared `AGENT_INTERNAL_SIGNING_KEY`) and then checks session
 * liveness before forwarding.
 */

import { INTERNAL_JWT_AUDIENCE, mintInternalJwt, verifyInternalJwt } from '../../runtime/internal-jwt'

export interface InferenceProxyClaims {
    sessionId: string
}

export async function mintInferenceProxyToken(opts: {
    sessionId: string
    signingKey: string
    /** Lifetime — cover the session's wall limit plus slack; mint per acquisition. */
    ttlSec: number
}): Promise<string> {
    return mintInternalJwt({
        audience: INTERNAL_JWT_AUDIENCE.INGRESS_INFERENCE,
        signingKey: opts.signingKey,
        claims: { session_id: opts.sessionId },
        ttlSec: opts.ttlSec,
    })
}

export async function verifyInferenceProxyToken(opts: {
    token: string
    signingKey: string
}): Promise<InferenceProxyClaims> {
    const payload = await verifyInternalJwt({
        token: opts.token,
        audience: INTERNAL_JWT_AUDIENCE.INGRESS_INFERENCE,
        signingKey: opts.signingKey,
    })
    const sessionId = payload.session_id
    if (typeof sessionId !== 'string' || sessionId.length === 0) {
        throw new Error('internal JWT verify failed: missing session_id claim')
    }
    return { sessionId }
}
