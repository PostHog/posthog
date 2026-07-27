/**
 * Signed-state token codec — a thin wrapper around `jose` that stamps an
 * HMAC-SHA256 JWT-compact-format token (`header.payload.signature`)
 * binding a `(user, purpose, payload)` triple plus expiry + nonce. Used
 * by the typed-confirm two-tool paradigm to carry confirmation state
 * through the LLM between a `prepare-X` and `execute-X` call.
 *
 * Claims:
 *   - `sub`     — user identity (mapped to JWT `sub`); binds the token to the authenticated principal
 *   - `purpose` — what the token is for, e.g. tool name (mapped to JWT `aud`); guards cross-purpose replay
 *   - `nonce`   — 128 random bits (mapped to JWT `jti`); the key for the single-use ledger
 *   - `iat/exp` — unix seconds; expiry caps the replay window
 *   - `payload` — caller-supplied opaque data, kept as a custom claim
 *
 * The token header is `{alg: 'HS256', typ: 'MCP-SIGNED-STATE'}` — `jose`
 * validates both at decode time so a token signed for a different purpose
 * or a different system (`typ`) can't be coerced into ours.
 *
 * One key: `MCP_SIGNED_STATE_KEY`. No encryption — confidentiality of
 * `payload` is the caller's responsibility.
 */

import { jwtVerify, SignJWT } from 'jose'
import { JOSEError, JWSSignatureVerificationFailed, JWTClaimValidationFailed, JWTExpired } from 'jose/errors'
import { randomBytes } from 'node:crypto'

import { DEFAULT_STATE_TTL_SECONDS, SIGNING_KEY_ENV_VAR, SIGNING_KEY_MIN_BYTES } from './constants'
import {
    SignedStateError,
    SignedStateExpired,
    SignedStateMalformed,
    SignedStatePurposeMismatch,
    SignedStateSignatureInvalid,
    SignedStateUserMismatch,
} from './errors'

const JWT_TYP = 'MCP-SIGNED-STATE'

export interface SignedStateClaims {
    sub: string
    purpose: string
    iat: number
    exp: number
    nonce: string
    payload: unknown
}

export interface SignedStateCodecOptions {
    /** TTL applied at encode time; default `DEFAULT_STATE_TTL_SECONDS`. */
    ttlSeconds?: number
    /** Override `Date.now()` for tests. */
    now?: () => number
    /** Override the entropy source for tests. */
    randomNonce?: () => string
}

export class SignedStateCodec {
    private readonly key: Uint8Array
    private readonly ttlSeconds: number
    private readonly now: () => number
    private readonly randomNonce: () => string

    constructor(key: Buffer | Uint8Array, options: SignedStateCodecOptions = {}) {
        this.key = key instanceof Uint8Array ? key : new Uint8Array(key)
        this.ttlSeconds = options.ttlSeconds ?? DEFAULT_STATE_TTL_SECONDS
        this.now = options.now ?? (() => Date.now())
        this.randomNonce = options.randomNonce ?? (() => randomBytes(16).toString('hex'))
    }

    /** Encode a fresh signed-state token bound to `(sub, purpose, payload)`. */
    async encode(input: {
        sub: string
        purpose: string
        payload: unknown
    }): Promise<{ token: string; claims: SignedStateClaims }> {
        const iat = Math.floor(this.now() / 1000)
        const exp = iat + this.ttlSeconds
        const nonce = this.randomNonce()
        const token = await new SignJWT({ payload: input.payload })
            .setProtectedHeader({ alg: 'HS256', typ: JWT_TYP })
            .setSubject(input.sub)
            .setAudience(input.purpose)
            .setIssuedAt(iat)
            .setExpirationTime(exp)
            .setJti(nonce)
            .sign(this.key)
        return {
            token,
            claims: { sub: input.sub, purpose: input.purpose, iat, exp, nonce, payload: input.payload },
        }
    }

    /**
     * Decode + verify an inbound token against the currently authenticated
     * (user, purpose). Throws `SignedStateError` subclasses for any
     * failure; the caller maps these to the appropriate response shape.
     */
    async decode(token: string, expectedSub: string, expectedPurpose: string): Promise<SignedStateClaims> {
        try {
            const { payload } = await jwtVerify(token, this.key, {
                algorithms: ['HS256'],
                typ: JWT_TYP,
                subject: expectedSub,
                audience: expectedPurpose,
                clockTolerance: 0,
                currentDate: new Date(this.now()),
            })
            // jose has already validated sub/aud/exp/typ; the cast is safe.
            return {
                sub: payload.sub as string,
                purpose: payload.aud as string,
                iat: payload.iat as number,
                exp: payload.exp as number,
                nonce: payload.jti as string,
                payload: (payload as { payload: unknown }).payload,
            }
        } catch (err) {
            throw mapJoseError(err)
        }
    }

    /**
     * Seconds until `claims.exp` according to the codec's clock —
     * guaranteed to be at least 1. Used by callers (e.g. the typed-confirm
     * nonce ledger) that need to size a TTL off the same time source the
     * codec used to stamp the token; reading the wall clock here would
     * skew under test injections or clock drift between the signer and
     * the consumer.
     */
    secondsUntilExpiry(claims: SignedStateClaims): number {
        const nowSeconds = Math.floor(this.now() / 1000)
        return Math.max(1, claims.exp - nowSeconds)
    }
}

/**
 * Load the signing key from the environment. Throws unconditionally if
 * the key is missing or under `SIGNING_KEY_MIN_BYTES`. No NODE_ENV gate
 * and no dev fallback — a deterministic placeholder would be publicly
 * known via this source file, so a leaked key would let any
 * authenticated user (or prompt-injected model) forge tokens for any
 * other user. Callers that want to boot without the paradigm available
 * should catch and continue (see `createApp` for the canonical pattern).
 */
export function loadSigningKeyFromEnv(env: NodeJS.ProcessEnv = process.env): Buffer {
    const raw = env[SIGNING_KEY_ENV_VAR] ?? ''
    const key = Buffer.from(raw, 'utf8')
    if (key.length < SIGNING_KEY_MIN_BYTES) {
        throw new Error(`${SIGNING_KEY_ENV_VAR} must be set to at least ${SIGNING_KEY_MIN_BYTES} bytes`)
    }
    return key
}

/**
 * Map jose's exception hierarchy onto our typed `SignedStateError`
 * subclasses. The runtime catches by class to drive metric labels and
 * user-facing refusal messages, so we want a stable, semantic mapping
 * rather than leaking jose's internal types upward.
 *
 * The `JWTClaimValidationFailed.claim` field tells us which standard
 * claim mismatched; we map `sub` and `aud` to our user/purpose flavors.
 * Anything else (malformed token, bad header) collapses to `Malformed`.
 */
function mapJoseError(err: unknown): SignedStateError {
    const message = err instanceof Error ? err.message : String(err)
    if (err instanceof JWTExpired) {
        return new SignedStateExpired(message)
    }
    if (err instanceof JWTClaimValidationFailed) {
        if (err.claim === 'sub') {
            return new SignedStateUserMismatch(message)
        }
        if (err.claim === 'aud') {
            return new SignedStatePurposeMismatch(message)
        }
        return new SignedStateMalformed(message)
    }
    if (err instanceof JWSSignatureVerificationFailed) {
        return new SignedStateSignatureInvalid(message)
    }
    if (err instanceof JOSEError) {
        return new SignedStateMalformed(message)
    }
    // Non-jose error: shouldn't happen in normal flow; surface as malformed
    // rather than swallowing or re-throwing an unknown type upward.
    return new SignedStateMalformed(message)
}
