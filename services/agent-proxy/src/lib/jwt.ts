// JWT verification for the agent-proxy service.
//
// Verify-only: this service never signs tokens. The private key is never loaded.
// Both legs (stream-read and sandbox event ingest) verify RS256 tokens against the
// public keys from SANDBOX_JWT_PUBLIC_KEY plus the optional SANDBOX_JWT_PUBLIC_KEY_SECONDARY
// (normalized in config.ts before reaching here).
//
// Zero-downtime key rotation: a token is verified against every configured public key in
// turn and accepted if any one validates the signature. This mirrors Django's
// SANDBOX_JWT_PRIVATE_KEY / _SECONDARY signing registry — during a rotation overlap the proxy
// trusts both the old and the new key, so flipping Django's primary signing key never rejects
// an in-flight token. jose ignores the token's kid for a concrete CryptoKey, so the keys are
// simply tried in order; only a signature mismatch advances to the next key (expiry, wrong
// audience and malformed claims are key-independent and fail fast).

import { errors, importSPKI, jwtVerify, type JWTPayload } from 'jose'

import { SANDBOX_EVENT_INGEST_AUDIENCE, STREAM_READ_AUDIENCE } from './constants.js'
import type { SandboxEventIngestTokenPayload, StreamReadTokenPayload } from './types.js'

// ---------------------------------------------------------------------------
// Public key loading
// ---------------------------------------------------------------------------

// Call once at startup with config.sandboxJwtPublicKeysPem (already normalized): the primary
// key first, then any rotation-secondary key. The returned CryptoKeys are cached by the caller
// for the process lifetime.
export async function loadPublicKeys(pemsRaw: string[]): Promise<CryptoKey[]> {
    return Promise.all(pemsRaw.map((pem) => importSPKI(pem, 'RS256')))
}

// ---------------------------------------------------------------------------
// Shared claim extraction
// ---------------------------------------------------------------------------

// Extract and validate the three required claims shared by both token types.
// Throws a plain Error (mapped to 401 by the server) on any claim type violation.
//
// Validation mirrors the Python validate_* helpers exactly:
//   - run_id: must be a string
//   - task_id: must be a string
//   - team_id: must be an integer (Number.isInteger rejects floats, booleans,
//     strings, null — booleans fail because typeof true === 'boolean', not
//     'number', so Number.isInteger(true) is false)
function assertStreamClaims(payload: Record<string, unknown>): { runId: string; taskId: string; teamId: number } {
    const runId = payload['run_id']
    const taskId = payload['task_id']
    const teamId = payload['team_id']

    if (typeof runId !== 'string') {
        throw new Error('Token has invalid claim: run_id must be a string')
    }
    if (typeof taskId !== 'string') {
        throw new Error('Token has invalid claim: task_id must be a string')
    }
    if (!Number.isInteger(teamId)) {
        throw new Error('Token has invalid claim: team_id must be an integer')
    }

    return { runId, taskId, teamId: teamId as number }
}

function assertPresenceGatedClaim(payload: Record<string, unknown>): boolean {
    const presenceGated = payload['presence_gated']
    if (presenceGated !== undefined && typeof presenceGated !== 'boolean') {
        throw new Error('Token has invalid claim: presence_gated must be a boolean')
    }
    return presenceGated ?? false
}

function assertIsTerminalClaim(payload: Record<string, unknown>): boolean {
    const isTerminal = payload['is_terminal']
    if (isTerminal !== undefined && typeof isTerminal !== 'boolean') {
        throw new Error('Token has invalid claim: is_terminal must be a boolean')
    }
    return isTerminal ?? false
}

function assertOriginProductClaim(payload: Record<string, unknown>): string {
    const originProduct = payload['origin_product']
    if (originProduct !== undefined && typeof originProduct !== 'string') {
        throw new Error('Token has invalid claim: origin_product must be a string')
    }
    return originProduct ?? 'unknown'
}

// Verify a token against every configured public key, returning the payload from the first key
// whose signature validates. Only a signature mismatch advances to the next key; expiry, wrong
// audience and malformed claims are key-independent and fail fast. This is what makes a
// primary-key rotation zero-downtime.
async function verifyWithKeys(token: string, publicKeys: CryptoKey[], audience: string): Promise<JWTPayload> {
    let lastSignatureError: unknown
    for (const key of publicKeys) {
        try {
            const { payload } = await jwtVerify(token, key, { algorithms: ['RS256'], audience })
            return payload
        } catch (err) {
            if (err instanceof errors.JWSSignatureVerificationFailed) {
                lastSignatureError = err
                continue
            }
            throw err
        }
    }
    throw lastSignatureError ?? new Error('Token signature verification failed: no public keys configured')
}

// ---------------------------------------------------------------------------
// Stream-read token  (GET /v1/runs/:run/stream leg)
// ---------------------------------------------------------------------------

// Audience: posthog:stream_read
// Required claims: run_id (string), task_id (string), team_id (integer)
// Optional claims: presence_gated (boolean, absent means false),
//                  is_terminal (boolean, absent means false),
//                  origin_product (string, absent means "unknown")
// Algorithm: RS256, no clockTolerance (matches Python leeway=0 default)
//
// Throws jose error subtypes (JWTExpired, JWTInvalid, JWSSignatureVerificationFailed,
// JWTClaimValidationFailed, etc.) on bad signature, wrong audience or expiry; throws
// a plain Error on malformed claim types. The server maps all of these to 401.
export async function validateStreamReadToken(token: string, publicKeys: CryptoKey[]): Promise<StreamReadTokenPayload> {
    const payload = await verifyWithKeys(token, publicKeys, STREAM_READ_AUDIENCE)
    const claims = payload as Record<string, unknown>
    return {
        ...assertStreamClaims(claims),
        presenceGated: assertPresenceGatedClaim(claims),
        isTerminal: assertIsTerminalClaim(claims),
        originProduct: assertOriginProductClaim(claims),
    }
}

// ---------------------------------------------------------------------------
// Sandbox event ingest token  (POST /v1/runs/:run/ingest leg)
// ---------------------------------------------------------------------------

// Audience: posthog:sandbox_event_ingest
// Required claims: run_id (string), task_id (string), team_id (integer)
// Optional claims: presence_gated (boolean, absent means false),
//                  origin_product (string, absent means "unknown")
// Algorithm: RS256, no clockTolerance (matches Python leeway=0 default)
//
// Same error semantics as validateStreamReadToken.
export async function validateSandboxEventIngestToken(
    token: string,
    publicKeys: CryptoKey[]
): Promise<SandboxEventIngestTokenPayload> {
    const payload = await verifyWithKeys(token, publicKeys, SANDBOX_EVENT_INGEST_AUDIENCE)
    const claims = payload as Record<string, unknown>
    return {
        ...assertStreamClaims(claims),
        presenceGated: assertPresenceGatedClaim(claims),
        originProduct: assertOriginProductClaim(claims),
    }
}
