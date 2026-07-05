/**
 * Plan confirmation token — a purpose-bound wrapper over `SignedStateCodec`.
 * The signed payload carries only `{ planHash, scriptHash }`; the script and
 * full plan live in the plan store, keyed by `scriptHash`, so the token stays
 * small. The codec is instantiated with a plan-appropriate 600s TTL via its
 * per-instance option rather than mutating the shared default.
 */

import {
    SignedStateCodec,
    type SignedStateCodecOptions,
    SignedStateError,
    SignedStateExpired,
} from '@/lib/signed-state'

/** Purpose claim binding these tokens to the apply flow (guards cross-purpose replay). */
export const PLAN_TOKEN_PURPOSE = 'exec-apply'

/** Plan-appropriate TTL: long enough to surface a plan and confirm, short enough to bound replay. */
export const PLAN_TOKEN_TTL_SECONDS = 600

export interface PlanTokenPayload {
    planHash: string
    scriptHash: string
}

/**
 * Build a codec dedicated to plan tokens. `ttlSeconds` defaults to
 * `PLAN_TOKEN_TTL_SECONDS`; tests may override `now`/`randomNonce` via options.
 */
export function createPlanTokenCodec(
    key: Buffer | Uint8Array,
    options: SignedStateCodecOptions = {}
): SignedStateCodec {
    return new SignedStateCodec(key, { ...options, ttlSeconds: options.ttlSeconds ?? PLAN_TOKEN_TTL_SECONDS })
}

export async function encodePlanToken(
    codec: SignedStateCodec,
    input: { sub: string; planHash: string; scriptHash: string }
): Promise<{ token: string; nonce: string }> {
    const payload: PlanTokenPayload = { planHash: input.planHash, scriptHash: input.scriptHash }
    const { token, claims } = await codec.encode({ sub: input.sub, purpose: PLAN_TOKEN_PURPOSE, payload })
    return { token, nonce: claims.nonce }
}

export type DecodePlanTokenResult =
    | {
          ok: true
          sub: string
          planHash: string
          scriptHash: string
          /** Nonce + remaining TTL, for the caller's single-use `NonceLedger`. */
          nonce: string
          secondsUntilExpiry: number
      }
    | { ok: false; reason: 'expired' }
    | { ok: false; reason: 'invalid'; kind: string; message: string }

/**
 * Verify a token against `(expectedSub, PLAN_TOKEN_PURPOSE)`. Expiry maps to a
 * dedicated `expired` result the caller can turn into an auto-re-plan; every
 * other signed-state failure collapses to `invalid`. Nonce single-use is the
 * caller's responsibility — the `nonce` and `secondsUntilExpiry` returned on
 * success are exactly what `NonceLedger.consume` needs.
 */
export async function decodePlanToken(
    codec: SignedStateCodec,
    token: string,
    expectedSub: string
): Promise<DecodePlanTokenResult> {
    try {
        const claims = await codec.decode(token, expectedSub, PLAN_TOKEN_PURPOSE)
        const payload = claims.payload
        if (!isPlanTokenPayload(payload)) {
            return { ok: false, reason: 'invalid', kind: 'malformed', message: 'Plan token payload is malformed' }
        }
        return {
            ok: true,
            sub: claims.sub,
            planHash: payload.planHash,
            scriptHash: payload.scriptHash,
            nonce: claims.nonce,
            secondsUntilExpiry: codec.secondsUntilExpiry(claims),
        }
    } catch (error) {
        if (error instanceof SignedStateExpired) {
            return { ok: false, reason: 'expired' }
        }
        if (error instanceof SignedStateError) {
            return { ok: false, reason: 'invalid', kind: error.kind, message: error.message }
        }
        throw error
    }
}

function isPlanTokenPayload(value: unknown): value is PlanTokenPayload {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as { planHash?: unknown }).planHash === 'string' &&
        typeof (value as { scriptHash?: unknown }).scriptHash === 'string'
    )
}
