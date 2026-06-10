/**
 * General-purpose signed-state token codec.
 *
 * Stamps an HMAC-SHA256 JWT-compact-format token (`header.payload.signature`)
 * binding a `(user, purpose, payload)` triple plus expiry + nonce. Used today
 * by the typed-confirm two-tool paradigm to carry confirmation state through
 * the LLM between a `prepare-X` and `execute-X` call; can be reused by any
 * future feature that needs to pass server-only state through an untrusted
 * client.
 *
 * Claims:
 *   - `sub`     — user identity, binds the token to the authenticated principal
 *   - `purpose` — what the token is for (e.g. tool name); guards cross-purpose replay
 *   - `payload` — caller-supplied opaque data (re-validated as untrusted on read)
 *   - `iat/exp` — unix seconds; expiry caps the replay window
 *   - `nonce`   — 128 random bits; the key for the single-use ledger
 *
 * Two keys may be configured: a primary (`MCP_SIGNED_STATE_KEY`, used for
 * sign + verify) and an optional secondary (`_OLD`, verify only) for
 * zero-downtime rotation. No encryption — confidentiality of `payload` is
 * the caller's responsibility.
 */

import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto'

import {
    DEFAULT_STATE_TTL_SECONDS,
    SIGNING_KEY_ENV_VAR,
    SIGNING_KEY_MIN_BYTES,
    SIGNING_KEY_OLD_ENV_VAR,
} from './constants'
import {
    SignedStateExpired,
    SignedStateMalformed,
    SignedStatePurposeMismatch,
    SignedStateSignatureInvalid,
    SignedStateUserMismatch,
} from './errors'

export interface SignedStateClaims {
    sub: string
    purpose: string
    iat: number
    exp: number
    nonce: string
    payload: unknown
}

interface TokenHeader {
    alg: 'HS256'
    typ: 'MCP-SIGNED-STATE'
}

const HEADER: TokenHeader = { alg: 'HS256', typ: 'MCP-SIGNED-STATE' }

export interface SignedStateCodecOptions {
    /** TTL applied at encode time; default `DEFAULT_STATE_TTL_SECONDS`. */
    ttlSeconds?: number
    /** Override `Date.now()` for tests. */
    now?: () => number
    /** Override the entropy source for tests. */
    randomNonce?: () => string
}

export class SignedStateCodec {
    private readonly primaryKey: Buffer
    private readonly secondaryKey: Buffer | undefined
    private readonly ttlSeconds: number
    private readonly now: () => number
    private readonly randomNonce: () => string

    constructor(primary: Buffer, secondary: Buffer | undefined, options: SignedStateCodecOptions = {}) {
        this.primaryKey = primary
        this.secondaryKey = secondary
        this.ttlSeconds = options.ttlSeconds ?? DEFAULT_STATE_TTL_SECONDS
        this.now = options.now ?? (() => Date.now())
        this.randomNonce = options.randomNonce ?? (() => randomBytes(16).toString('hex'))
    }

    /** Encode a fresh signed-state token bound to `(sub, purpose, payload)`. */
    encode(input: { sub: string; purpose: string; payload: unknown }): { token: string; claims: SignedStateClaims } {
        const nowSeconds = Math.floor(this.now() / 1000)
        const claims: SignedStateClaims = {
            sub: input.sub,
            purpose: input.purpose,
            iat: nowSeconds,
            exp: nowSeconds + this.ttlSeconds,
            nonce: this.randomNonce(),
            payload: input.payload,
        }
        const headerB64 = base64UrlEncode(JSON.stringify(HEADER))
        const payloadB64 = base64UrlEncode(JSON.stringify(claims))
        const signingInput = `${headerB64}.${payloadB64}`
        const signature = sign(signingInput, this.primaryKey)
        return { token: `${signingInput}.${signature}`, claims }
    }

    /**
     * Decode + verify an inbound token against the currently authenticated
     * (user, purpose). Throws `SignedStateError` subclasses for any failure;
     * the caller maps these to the appropriate response shape.
     */
    decode(token: string, expectedSub: string, expectedPurpose: string): SignedStateClaims {
        const parts = token.split('.')
        if (parts.length !== 3) {
            throw new SignedStateMalformed('Token must have three dot-separated segments')
        }
        const [headerB64, payloadB64, signatureB64] = parts as [string, string, string]

        const signingInput = `${headerB64}.${payloadB64}`
        if (!verify(signingInput, signatureB64, this.primaryKey, this.secondaryKey)) {
            throw new SignedStateSignatureInvalid('Signature does not match any configured key')
        }

        let parsedHeader: unknown
        let parsedClaims: unknown
        try {
            parsedHeader = JSON.parse(base64UrlDecode(headerB64).toString('utf8'))
            parsedClaims = JSON.parse(base64UrlDecode(payloadB64).toString('utf8'))
        } catch {
            throw new SignedStateMalformed('Header or payload is not valid JSON')
        }
        if (!isTokenHeader(parsedHeader)) {
            throw new SignedStateMalformed('Header alg/typ mismatch')
        }
        const claims = asClaims(parsedClaims)

        const nowSeconds = Math.floor(this.now() / 1000)
        if (claims.exp <= nowSeconds) {
            throw new SignedStateExpired(`Expired at ${claims.exp}; now=${nowSeconds}`)
        }
        if (!timingSafeStringEqual(claims.sub, expectedSub)) {
            throw new SignedStateUserMismatch('Token sub does not match the authenticated user')
        }
        if (!timingSafeStringEqual(claims.purpose, expectedPurpose)) {
            throw new SignedStatePurposeMismatch('Token purpose does not match the invoked tool/operation')
        }
        return claims
    }
}

/**
 * Load signing keys from the environment. In production, refuses to start
 * without a key of sufficient length (mirrors Django `SECRET_KEY` guard).
 * In dev/test, falls back to a loud-warning placeholder.
 */
export function loadSigningKeysFromEnv(env: NodeJS.ProcessEnv = process.env): {
    primary: Buffer
    secondary: Buffer | undefined
} {
    const primaryRaw = env[SIGNING_KEY_ENV_VAR] ?? ''
    const primary = Buffer.from(primaryRaw, 'utf8')
    if (primary.length < SIGNING_KEY_MIN_BYTES) {
        if (env.NODE_ENV === 'production') {
            throw new Error(
                `${SIGNING_KEY_ENV_VAR} must be set to at least ${SIGNING_KEY_MIN_BYTES} bytes in production`
            )
        }
        console.warn(
            `[signed-state] ${SIGNING_KEY_ENV_VAR} not set or too short; using insecure dev placeholder. Never deploy this.`
        )
        return {
            primary: Buffer.from('dev-placeholder-signing-key-do-not-use-in-prod', 'utf8'),
            secondary: undefined,
        }
    }
    const secondaryRaw = env[SIGNING_KEY_OLD_ENV_VAR]
    const secondary =
        secondaryRaw && secondaryRaw.length >= SIGNING_KEY_MIN_BYTES ? Buffer.from(secondaryRaw, 'utf8') : undefined
    return { primary, secondary }
}

// --- helpers ---

function sign(input: string, key: Buffer): string {
    return base64UrlEncode(createHmac('sha256', key).update(input).digest())
}

function verify(input: string, signatureB64: string, primary: Buffer, secondary: Buffer | undefined): boolean {
    const provided = base64UrlDecode(signatureB64)
    const primarySig = createHmac('sha256', primary).update(input).digest()
    if (constantTimeEqual(provided, primarySig)) {
        return true
    }
    if (secondary) {
        const secondarySig = createHmac('sha256', secondary).update(input).digest()
        if (constantTimeEqual(provided, secondarySig)) {
            return true
        }
    }
    return false
}

function constantTimeEqual(a: Buffer, b: Buffer): boolean {
    if (a.length !== b.length) {
        return false
    }
    return timingSafeEqual(a, b)
}

function timingSafeStringEqual(a: string, b: string): boolean {
    const aBuf = Buffer.from(a, 'utf8')
    const bBuf = Buffer.from(b, 'utf8')
    return constantTimeEqual(aBuf, bBuf)
}

function base64UrlEncode(input: string | Buffer): string {
    const buf = typeof input === 'string' ? Buffer.from(input, 'utf8') : input
    return buf.toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_')
}

function base64UrlDecode(input: string): Buffer {
    const padded = input + '='.repeat((4 - (input.length % 4)) % 4)
    return Buffer.from(padded.replace(/-/g, '+').replace(/_/g, '/'), 'base64')
}

function isTokenHeader(value: unknown): value is TokenHeader {
    if (value === null || typeof value !== 'object') {
        return false
    }
    const obj = value as Record<string, unknown>
    return obj['alg'] === 'HS256' && obj['typ'] === 'MCP-SIGNED-STATE'
}

function asClaims(value: unknown): SignedStateClaims {
    if (value === null || typeof value !== 'object') {
        throw new SignedStateMalformed('Payload is not an object')
    }
    const obj = value as Record<string, unknown>
    if (
        typeof obj['sub'] !== 'string' ||
        typeof obj['purpose'] !== 'string' ||
        typeof obj['iat'] !== 'number' ||
        typeof obj['exp'] !== 'number' ||
        typeof obj['nonce'] !== 'string'
    ) {
        throw new SignedStateMalformed('Payload is missing required claims')
    }
    return obj as unknown as SignedStateClaims
}
