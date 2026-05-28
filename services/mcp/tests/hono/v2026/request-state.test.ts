import { describe, expect, it } from 'vitest'

import { MAX_REQUEST_STATE_ROUNDS, REQUEST_STATE_TTL_SECONDS } from '@/hono/v2026/constants'
import {
    RequestStateExpired,
    RequestStateMalformed,
    RequestStateRoundsExceeded,
    RequestStateSignatureInvalid,
    RequestStateToolMismatch,
    RequestStateUserMismatch,
} from '@/hono/v2026/errors'
import { RequestStateCodec, loadSigningKeysFromEnv } from '@/hono/v2026/request-state'

function makeCodec(now: number = 1_700_000_000_000): {
    codec: RequestStateCodec
    advance: (deltaMs: number) => void
} {
    const key = Buffer.alloc(32, 0x42)
    let clock = now
    const codec = new RequestStateCodec(key, undefined, {
        now: () => clock,
        randomNonce: () => 'fixed-nonce-for-tests',
    })
    return { codec, advance: (deltaMs) => (clock += deltaMs) }
}

describe('RequestStateCodec', () => {
    it('round-trips claims through encode + decode', () => {
        const { codec } = makeCodec()
        const token = codec.encode({ sub: 'user-1', tool: 'org-update', round: 0, payload: { step: 1 } })
        const decoded = codec.decode(token, 'user-1', 'org-update')
        expect(decoded.sub).toBe('user-1')
        expect(decoded.tool).toBe('org-update')
        expect(decoded.round).toBe(0)
        expect(decoded.payload).toEqual({ step: 1 })
        expect(decoded.exp).toBe(decoded.iat + REQUEST_STATE_TTL_SECONDS)
    })

    it('rejects a token whose signature was tampered with', () => {
        const { codec } = makeCodec()
        const token = codec.encode({ sub: 'user-1', tool: 'org-update', round: 0, payload: null })
        // Flip a character in the signature segment.
        const segments = token.split('.')
        const sig = segments[2]!
        const tampered = `${segments[0]}.${segments[1]}.${sig.slice(0, -1)}${sig.slice(-1) === 'A' ? 'B' : 'A'}`
        expect(() => codec.decode(tampered, 'user-1', 'org-update')).toThrow(RequestStateSignatureInvalid)
    })

    it('rejects a token whose payload was tampered with', () => {
        const { codec } = makeCodec()
        const token = codec.encode({ sub: 'user-1', tool: 'org-update', round: 0, payload: null })
        const [header, _payload, sig] = token.split('.')
        // Replace the payload with a different base64-encoded claims blob.
        const forged = Buffer.from(
            JSON.stringify({
                sub: 'user-2',
                tool: 'org-update',
                round: 0,
                iat: 0,
                exp: 9_999_999_999,
                nonce: 'x',
                payload: null,
            }),
            'utf8'
        )
            .toString('base64')
            .replace(/=/g, '')
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
        expect(() => codec.decode(`${header}.${forged}.${sig}`, 'user-2', 'org-update')).toThrow(
            RequestStateSignatureInvalid
        )
    })

    it('rejects a token after exp has passed', () => {
        const { codec, advance } = makeCodec()
        const token = codec.encode({ sub: 'user-1', tool: 'org-update', round: 0, payload: null })
        advance((REQUEST_STATE_TTL_SECONDS + 1) * 1000)
        expect(() => codec.decode(token, 'user-1', 'org-update')).toThrow(RequestStateExpired)
    })

    it('rejects a token replayed under a different authenticated user', () => {
        const { codec } = makeCodec()
        const token = codec.encode({ sub: 'user-1', tool: 'org-update', round: 0, payload: null })
        expect(() => codec.decode(token, 'user-attacker', 'org-update')).toThrow(RequestStateUserMismatch)
    })

    it('rejects a token replayed against a different tool', () => {
        const { codec } = makeCodec()
        const token = codec.encode({ sub: 'user-1', tool: 'org-update', round: 0, payload: null })
        expect(() => codec.decode(token, 'user-1', 'other-tool')).toThrow(RequestStateToolMismatch)
    })

    it('rejects a token whose round counter already reached the cap', () => {
        const { codec } = makeCodec()
        const token = codec.encode({
            sub: 'user-1',
            tool: 'org-update',
            round: MAX_REQUEST_STATE_ROUNDS,
            payload: null,
        })
        expect(() => codec.decode(token, 'user-1', 'org-update')).toThrow(RequestStateRoundsExceeded)
    })

    it('allows the last legal round (cap - 1)', () => {
        const { codec } = makeCodec()
        const token = codec.encode({
            sub: 'user-1',
            tool: 'org-update',
            round: MAX_REQUEST_STATE_ROUNDS - 1,
            payload: null,
        })
        const decoded = codec.decode(token, 'user-1', 'org-update')
        expect(decoded.round).toBe(MAX_REQUEST_STATE_ROUNDS - 1)
    })

    it('rejects malformed tokens (wrong segment count)', () => {
        const { codec } = makeCodec()
        expect(() => codec.decode('only.two', 'user-1', 'tool')).toThrow(RequestStateMalformed)
        expect(() => codec.decode('a.b.c.d', 'user-1', 'tool')).toThrow(RequestStateMalformed)
        expect(() => codec.decode('', 'user-1', 'tool')).toThrow(RequestStateMalformed)
    })

    it('rejects a token whose header has the wrong alg', () => {
        const { codec } = makeCodec()
        const header = Buffer.from(JSON.stringify({ alg: 'none', typ: 'MCP-REQ-STATE' }), 'utf8')
            .toString('base64')
            .replace(/=/g, '')
            .replace(/\+/g, '-')
            .replace(/\//g, '_')
        const token = codec.encode({ sub: 'user-1', tool: 'tool', round: 0, payload: null })
        const [, payload, sig] = token.split('.')
        // Re-sign would require the same key, so we expect the tampered header
        // to fail the signature check OR the alg check. Either rejection is OK
        // for the spec — both are "malformed/invalid".
        expect(() => codec.decode(`${header}.${payload}.${sig}`, 'user-1', 'tool')).toThrow()
    })
})

describe('RequestStateCodec — key rotation', () => {
    it('verifies tokens signed with the secondary key', () => {
        const primary = Buffer.alloc(32, 0x11)
        const secondary = Buffer.alloc(32, 0x22)
        const oldCodec = new RequestStateCodec(secondary, undefined, { now: () => 1_700_000_000_000 })
        const newCodec = new RequestStateCodec(primary, secondary, { now: () => 1_700_000_000_000 })

        const token = oldCodec.encode({ sub: 'user-1', tool: 'tool', round: 0, payload: null })
        // The rotated server (primary + secondary) accepts the old token.
        const decoded = newCodec.decode(token, 'user-1', 'tool')
        expect(decoded.sub).toBe('user-1')
    })

    it('signs new tokens with the primary key only, not the secondary', () => {
        const primary = Buffer.alloc(32, 0x11)
        const secondary = Buffer.alloc(32, 0x22)
        const onlyOld = new RequestStateCodec(secondary, undefined, { now: () => 1_700_000_000_000 })
        const rotated = new RequestStateCodec(primary, secondary, { now: () => 1_700_000_000_000 })

        // A token freshly signed by the rotated server must NOT verify against
        // the old key alone — only the primary, or another rotated server.
        const token = rotated.encode({ sub: 'user-1', tool: 'tool', round: 0, payload: null })
        expect(() => onlyOld.decode(token, 'user-1', 'tool')).toThrow(RequestStateSignatureInvalid)
    })
})

describe('loadSigningKeysFromEnv', () => {
    it('throws in production when the key is missing', () => {
        expect(() => loadSigningKeysFromEnv({ NODE_ENV: 'production' })).toThrow(/must be set to at least/)
    })

    it('throws in production when the key is too short', () => {
        expect(() =>
            loadSigningKeysFromEnv({ NODE_ENV: 'production', MCP_REQUEST_STATE_SIGNING_KEY: 'short' })
        ).toThrow(/must be set to at least/)
    })

    it('returns the placeholder in non-production when the key is missing', () => {
        const { primary, secondary } = loadSigningKeysFromEnv({ NODE_ENV: 'development' })
        expect(primary.length).toBeGreaterThan(0)
        expect(secondary).toBeUndefined()
    })

    it('returns the primary key when sufficiently long', () => {
        const longKey = 'a'.repeat(32)
        const { primary } = loadSigningKeysFromEnv({
            NODE_ENV: 'production',
            MCP_REQUEST_STATE_SIGNING_KEY: longKey,
        })
        expect(primary.toString('utf8')).toBe(longKey)
    })

    it('returns the secondary key when configured and long enough', () => {
        const longKey = 'a'.repeat(32)
        const longOld = 'b'.repeat(32)
        const { secondary } = loadSigningKeysFromEnv({
            NODE_ENV: 'production',
            MCP_REQUEST_STATE_SIGNING_KEY: longKey,
            MCP_REQUEST_STATE_SIGNING_KEY_OLD: longOld,
        })
        expect(secondary?.toString('utf8')).toBe(longOld)
    })

    it('ignores a too-short secondary key', () => {
        const longKey = 'a'.repeat(32)
        const { secondary } = loadSigningKeysFromEnv({
            NODE_ENV: 'production',
            MCP_REQUEST_STATE_SIGNING_KEY: longKey,
            MCP_REQUEST_STATE_SIGNING_KEY_OLD: 'short',
        })
        expect(secondary).toBeUndefined()
    })
})
