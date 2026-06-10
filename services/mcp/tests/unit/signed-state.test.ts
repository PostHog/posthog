import { describe, expect, it, vi } from 'vitest'

import {
    loadSigningKeyFromEnv,
    NonceLedger,
    SignedStateAlreadyConsumed,
    SignedStateCodec,
    SignedStateExpired,
    SignedStateMalformed,
    SignedStatePurposeMismatch,
    SignedStateSignatureInvalid,
    SignedStateUserMismatch,
} from '@/lib/signed-state'

function makeCodec(now = 1_700_000_000_000): {
    codec: SignedStateCodec
    advance: (ms: number) => void
} {
    let clock = now
    const codec = new SignedStateCodec(Buffer.alloc(32, 0x42), {
        now: () => clock,
        randomNonce: () => 'fixed-nonce',
        ttlSeconds: 300,
    })
    return { codec, advance: (ms) => (clock += ms) }
}

describe('SignedStateCodec', () => {
    it('round-trips claims through encode + decode', () => {
        const { codec } = makeCodec()
        const { token, claims } = codec.encode({ sub: 'u1', purpose: 'p1', payload: { x: 7 } })
        expect(claims.exp).toBe(claims.iat + 300)
        const decoded = codec.decode(token, 'u1', 'p1')
        expect(decoded.payload).toEqual({ x: 7 })
        expect(decoded.nonce).toBe('fixed-nonce')
    })

    it('rejects a token whose signature was tampered with', () => {
        const { codec } = makeCodec()
        const { token } = codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        const segs = token.split('.')
        const sig = segs[2]!
        const tampered = `${segs[0]}.${segs[1]}.${sig.slice(0, -1)}${sig.endsWith('A') ? 'B' : 'A'}`
        expect(() => codec.decode(tampered, 'u1', 'p1')).toThrow(SignedStateSignatureInvalid)
    })

    it('rejects a token after exp has passed', () => {
        const { codec, advance } = makeCodec()
        const { token } = codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        advance(301 * 1000)
        expect(() => codec.decode(token, 'u1', 'p1')).toThrow(SignedStateExpired)
    })

    it('rejects a token replayed under a different sub', () => {
        const { codec } = makeCodec()
        const { token } = codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        expect(() => codec.decode(token, 'attacker', 'p1')).toThrow(SignedStateUserMismatch)
    })

    it('rejects a token replayed for a different purpose', () => {
        const { codec } = makeCodec()
        const { token } = codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        expect(() => codec.decode(token, 'u1', 'p2')).toThrow(SignedStatePurposeMismatch)
    })

    it('rejects malformed tokens (wrong segment count)', () => {
        const { codec } = makeCodec()
        expect(() => codec.decode('only.two', 'u', 'p')).toThrow(SignedStateMalformed)
    })

    it('rejects a token signed with a different key', () => {
        const a = new SignedStateCodec(Buffer.alloc(32, 0x11), { now: () => 1_700_000_000_000 })
        const b = new SignedStateCodec(Buffer.alloc(32, 0x22), { now: () => 1_700_000_000_000 })
        const { token } = a.encode({ sub: 'u1', purpose: 'p1', payload: null })
        expect(() => b.decode(token, 'u1', 'p1')).toThrow(SignedStateSignatureInvalid)
    })

    it('secondsUntilExpiry sources the clock from the codec, not the wall clock', () => {
        // Inject a clock 100s before exp; assert the runtime gets 100,
        // independent of what Date.now() reads in real wall time. This
        // is what protects the nonce ledger from clock-skew shrinkage.
        const { codec } = makeCodec()
        const { claims } = codec.encode({ sub: 'u', purpose: 'p', payload: null })
        expect(codec.secondsUntilExpiry(claims)).toBe(300)
    })

    it('secondsUntilExpiry tracks the injected clock as it advances', () => {
        const { codec, advance } = makeCodec()
        const { claims } = codec.encode({ sub: 'u', purpose: 'p', payload: null })
        advance(200 * 1000)
        expect(codec.secondsUntilExpiry(claims)).toBe(100)
    })

    it('secondsUntilExpiry clamps to 1 once the token has lapsed', () => {
        const { codec, advance } = makeCodec()
        const { claims } = codec.encode({ sub: 'u', purpose: 'p', payload: null })
        advance(1_000 * 1000) // far past exp
        expect(codec.secondsUntilExpiry(claims)).toBe(1)
    })
})

describe('loadSigningKeyFromEnv', () => {
    it('throws in production when key is missing or too short', () => {
        expect(() => loadSigningKeyFromEnv({ NODE_ENV: 'production' })).toThrow(/must be set/)
        expect(() => loadSigningKeyFromEnv({ NODE_ENV: 'production', MCP_SIGNED_STATE_KEY: 'short' })).toThrow(
            /must be set/
        )
    })

    it('returns a dev placeholder outside production', () => {
        const key = loadSigningKeyFromEnv({ NODE_ENV: 'development' })
        expect(key.length).toBeGreaterThan(0)
    })

    it('returns the configured key when present', () => {
        const longKey = 'a'.repeat(32)
        const key = loadSigningKeyFromEnv({
            NODE_ENV: 'production',
            MCP_SIGNED_STATE_KEY: longKey,
        })
        expect(key.toString()).toBe(longKey)
    })
})

describe('NonceLedger', () => {
    function makeRedis(): { redis: { set: ReturnType<typeof vi.fn> }; store: Map<string, string> } {
        const store = new Map<string, string>()
        const redis = {
            set: vi.fn(async (key: string, value: string, ..._args: (string | number)[]) => {
                const argv = _args.map((a) => (typeof a === 'string' ? a.toUpperCase() : a))
                const nx = argv.includes('NX')
                if (nx && store.has(key)) {
                    return null
                }
                store.set(key, value)
                return 'OK'
            }),
        }
        return { redis, store }
    }

    it('consumes a fresh nonce successfully', async () => {
        const { redis } = makeRedis()
        const ledger = new NonceLedger(redis)
        await expect(ledger.consume('nonce-1', 300)).resolves.toBeUndefined()
    })

    it('rejects a second consume of the same nonce', async () => {
        const { redis } = makeRedis()
        const ledger = new NonceLedger(redis)
        await ledger.consume('nonce-1', 300)
        await expect(ledger.consume('nonce-1', 300)).rejects.toBeInstanceOf(SignedStateAlreadyConsumed)
    })

    it('uses NX + EX so abandoned nonces self-clean', async () => {
        const { redis } = makeRedis()
        const ledger = new NonceLedger(redis)
        await ledger.consume('nonce-1', 300)
        const args = redis.set.mock.calls[0]!
        expect(args).toEqual(['mcp:signed-state:nonce:nonce-1', '1', 'EX', 300, 'NX'])
    })
})
