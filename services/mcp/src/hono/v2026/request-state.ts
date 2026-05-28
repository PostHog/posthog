/**
 * `requestState` codec for the v2026 MCP pipeline.
 *
 * Encodes a small set of HMAC-signed claims into a JWT-compact-format token
 * (`header.payload.signature`) that the server stamps into every
 * `InputRequiredResult` and validates on every retry. The token carries:
 *
 *   - `sub`   — userHash, binding the state to the authenticated principal
 *   - `tool`  — tool name, blocking cross-tool replay
 *   - `round` — monotonic counter capped at MAX_REQUEST_STATE_ROUNDS
 *   - `iat`   — issued-at, unix seconds
 *   - `exp`   — iat + REQUEST_STATE_TTL_SECONDS
 *   - `nonce` — 128 random bits
 *   - `payload` — opaque tool-author state, re-validated as untrusted on read
 *
 * Signed with HMAC-SHA256. Two keys may be configured: the primary
 * (`MCP_REQUEST_STATE_SIGNING_KEY`) is used for both sign + verify; an
 * optional secondary (`MCP_REQUEST_STATE_SIGNING_KEY_OLD`) is verify-only,
 * enabling zero-downtime rotation. The codec does NOT encrypt — confidentiality
 * of `payload` is the tool author's responsibility.
 */

import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto'

import {
    MAX_REQUEST_STATE_ROUNDS,
    REQUEST_STATE_TTL_SECONDS,
    SIGNING_KEY_ENV_VAR,
    SIGNING_KEY_MIN_BYTES,
    SIGNING_KEY_OLD_ENV_VAR,
} from './constants'
import {
    RequestStateExpired,
    RequestStateMalformed,
    RequestStateRoundsExceeded,
    RequestStateSignatureInvalid,
    RequestStateToolMismatch,
    RequestStateUserMismatch,
} from './errors'

export interface RequestStateClaims {
    sub: string
    tool: string
    round: number
    iat: number
    exp: number
    nonce: string
    payload: unknown
}

interface RequestStateHeader {
    alg: 'HS256'
    typ: 'MCP-REQ-STATE'
}

const HEADER: RequestStateHeader = { alg: 'HS256', typ: 'MCP-REQ-STATE' }

export interface CodecOptions {
    /** Override `Date.now()` for tests. */
    now?: () => number
    /** Override the entropy source for tests. */
    randomNonce?: () => string
}

/**
 * Stateless codec — pure functions of the configured keys + options. Created
 * once at startup and reused.
 */
export class RequestStateCodec {
    private readonly primaryKey: Buffer
    private readonly secondaryKey: Buffer | undefined
    private readonly now: () => number
    private readonly randomNonce: () => string

    constructor(primary: Buffer, secondary: Buffer | undefined, options: CodecOptions = {}) {
        this.primaryKey = primary
        this.secondaryKey = secondary
        this.now = options.now ?? (() => Date.now())
        this.randomNonce = options.randomNonce ?? (() => randomBytes(16).toString('hex'))
    }

    /**
     * Encode a fresh `requestState` token bound to the (user, tool, round).
     * `payload` is whatever the tool author wants to carry forward; it
     * round-trips through the client opaquely.
     */
    encode(input: { sub: string; tool: string; round: number; payload: unknown }): string {
        const nowSeconds = Math.floor(this.now() / 1000)
        const claims: RequestStateClaims = {
            sub: input.sub,
            tool: input.tool,
            round: input.round,
            iat: nowSeconds,
            exp: nowSeconds + REQUEST_STATE_TTL_SECONDS,
            nonce: this.randomNonce(),
            payload: input.payload,
        }
        const headerB64 = base64UrlEncode(JSON.stringify(HEADER))
        const payloadB64 = base64UrlEncode(JSON.stringify(claims))
        const signingInput = `${headerB64}.${payloadB64}`
        const signature = sign(signingInput, this.primaryKey)
        return `${signingInput}.${signature}`
    }

    /**
     * Decode + verify an inbound token against the currently authenticated
     * (user, tool). Throws `RequestStateError` subclasses for any failure
     * mode — the dispatcher maps these to JSON-RPC error responses.
     */
    decode(token: string, expectedSub: string, expectedTool: string): RequestStateClaims {
        const parts = token.split('.')
        if (parts.length !== 3) {
            throw new RequestStateMalformed('requestState token must have three dot-separated segments')
        }
        const [headerB64, payloadB64, signatureB64] = parts as [string, string, string]

        const signingInput = `${headerB64}.${payloadB64}`
        if (!verify(signingInput, signatureB64, this.primaryKey, this.secondaryKey)) {
            throw new RequestStateSignatureInvalid('requestState signature does not match any configured key')
        }

        let parsedHeader: unknown
        let parsedClaims: unknown
        try {
            parsedHeader = JSON.parse(base64UrlDecode(headerB64).toString('utf8'))
            parsedClaims = JSON.parse(base64UrlDecode(payloadB64).toString('utf8'))
        } catch {
            throw new RequestStateMalformed('requestState header or payload is not valid JSON')
        }
        if (!isMcpHeader(parsedHeader)) {
            throw new RequestStateMalformed('requestState header alg/typ mismatch')
        }
        const claims = asClaims(parsedClaims)

        const nowSeconds = Math.floor(this.now() / 1000)
        if (claims.exp <= nowSeconds) {
            throw new RequestStateExpired(`requestState expired at ${claims.exp}, now=${nowSeconds}`)
        }
        if (!timingSafeStringEqual(claims.sub, expectedSub)) {
            throw new RequestStateUserMismatch('requestState sub does not match the authenticated user')
        }
        if (!timingSafeStringEqual(claims.tool, expectedTool)) {
            throw new RequestStateToolMismatch('requestState tool does not match the invoked tool')
        }
        if (claims.round >= MAX_REQUEST_STATE_ROUNDS) {
            throw new RequestStateRoundsExceeded(
                `requestState round ${claims.round} >= cap ${MAX_REQUEST_STATE_ROUNDS}`
            )
        }
        return claims
    }
}

/**
 * Load the signing keys from the environment. Fails loud in production when
 * the primary is missing or too short — mirrors Django's `SECRET_KEY` guard.
 * Returns `undefined` for the secondary if it isn't configured.
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
        // Non-production: warn + use a placeholder so dev/test still work.
        // The placeholder is deterministic so encoded tokens roundtrip across
        // restarts; production must never see this branch.
        console.warn(
            `[v2026] ${SIGNING_KEY_ENV_VAR} not set or too short; using insecure dev placeholder. Never deploy this.`
        )
        return { primary: Buffer.from('dev-placeholder-key-do-not-use-in-prod', 'utf8'), secondary: undefined }
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

function isMcpHeader(value: unknown): value is RequestStateHeader {
    if (value === null || typeof value !== 'object') {
        return false
    }
    const obj = value as Record<string, unknown>
    return obj['alg'] === 'HS256' && obj['typ'] === 'MCP-REQ-STATE'
}

function asClaims(value: unknown): RequestStateClaims {
    if (value === null || typeof value !== 'object') {
        throw new RequestStateMalformed('requestState payload is not an object')
    }
    const obj = value as Record<string, unknown>
    if (
        typeof obj['sub'] !== 'string' ||
        typeof obj['tool'] !== 'string' ||
        typeof obj['round'] !== 'number' ||
        typeof obj['iat'] !== 'number' ||
        typeof obj['exp'] !== 'number' ||
        typeof obj['nonce'] !== 'string'
    ) {
        throw new RequestStateMalformed('requestState payload is missing required claims')
    }
    return obj as unknown as RequestStateClaims
}
