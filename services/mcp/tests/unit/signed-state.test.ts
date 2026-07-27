import { describe, expect, it, type Mock, vi } from 'vitest'

import {
    loadSigningKeyFromEnv,
    NonceLedger,
    type NonceLedgerRedis,
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
    it('round-trips claims through encode + decode', async () => {
        const { codec } = makeCodec()
        const { token, claims } = await codec.encode({ sub: 'u1', purpose: 'p1', payload: { x: 7 } })
        expect(claims.exp).toBe(claims.iat + 300)
        const decoded = await codec.decode(token, 'u1', 'p1')
        expect(decoded.payload).toEqual({ x: 7 })
        expect(decoded.nonce).toBe('fixed-nonce')
    })

    it('rejects a token whose signature was tampered with', async () => {
        const { codec } = makeCodec()
        const { token } = await codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        const segs = token.split('.')
        const sig = segs[2]!
        const tampered = `${segs[0]}.${segs[1]}.${sig.slice(0, -1)}${sig.endsWith('A') ? 'B' : 'A'}`
        await expect(codec.decode(tampered, 'u1', 'p1')).rejects.toBeInstanceOf(SignedStateSignatureInvalid)
    })

    it('rejects a token after exp has passed', async () => {
        const { codec, advance } = makeCodec()
        const { token } = await codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        advance(301 * 1000)
        await expect(codec.decode(token, 'u1', 'p1')).rejects.toBeInstanceOf(SignedStateExpired)
    })

    it('rejects a token replayed under a different sub', async () => {
        const { codec } = makeCodec()
        const { token } = await codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        await expect(codec.decode(token, 'attacker', 'p1')).rejects.toBeInstanceOf(SignedStateUserMismatch)
    })

    it('rejects a token replayed for a different purpose', async () => {
        const { codec } = makeCodec()
        const { token } = await codec.encode({ sub: 'u1', purpose: 'p1', payload: null })
        await expect(codec.decode(token, 'u1', 'p2')).rejects.toBeInstanceOf(SignedStatePurposeMismatch)
    })

    it('rejects malformed tokens (wrong segment count)', async () => {
        const { codec } = makeCodec()
        await expect(codec.decode('only.two', 'u', 'p')).rejects.toBeInstanceOf(SignedStateMalformed)
    })

    it('rejects a token signed with a different key', async () => {
        const a = new SignedStateCodec(Buffer.alloc(32, 0x11), { now: () => 1_700_000_000_000 })
        const b = new SignedStateCodec(Buffer.alloc(32, 0x22), { now: () => 1_700_000_000_000 })
        const { token } = await a.encode({ sub: 'u1', purpose: 'p1', payload: null })
        await expect(b.decode(token, 'u1', 'p1')).rejects.toBeInstanceOf(SignedStateSignatureInvalid)
    })

    it('secondsUntilExpiry sources the clock from the codec, not the wall clock', async () => {
        // Inject a clock 100s before exp; assert the runtime gets 100,
        // independent of what Date.now() reads in real wall time. This
        // is what protects the nonce ledger from clock-skew shrinkage.
        const { codec } = makeCodec()
        const { claims } = await codec.encode({ sub: 'u', purpose: 'p', payload: null })
        expect(codec.secondsUntilExpiry(claims)).toBe(300)
    })

    it('secondsUntilExpiry tracks the injected clock as it advances', async () => {
        const { codec, advance } = makeCodec()
        const { claims } = await codec.encode({ sub: 'u', purpose: 'p', payload: null })
        advance(200 * 1000)
        expect(codec.secondsUntilExpiry(claims)).toBe(100)
    })

    it('secondsUntilExpiry clamps to 1 once the token has lapsed', async () => {
        const { codec, advance } = makeCodec()
        const { claims } = await codec.encode({ sub: 'u', purpose: 'p', payload: null })
        advance(1_000 * 1000) // far past exp
        expect(codec.secondsUntilExpiry(claims)).toBe(1)
    })

    it('rejects a token whose protected header typ is wrong (cross-system replay)', async () => {
        // jose pins the typ header on verify — this protects against
        // someone feeding us a token signed for a different MCP feature
        // that happens to share the same key.
        const key = Buffer.alloc(32, 0x42)
        const { SignJWT } = await import('jose')
        const foreignToken = await new SignJWT({})
            .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
            .setSubject('u1')
            .setAudience('p1')
            .setIssuedAt(1_700_000_000)
            .setExpirationTime(1_700_000_300)
            .setJti('n')
            .sign(new Uint8Array(key))
        const codec = new SignedStateCodec(key, { now: () => 1_700_000_000_000 })
        await expect(codec.decode(foreignToken, 'u1', 'p1')).rejects.toBeInstanceOf(SignedStateMalformed)
    })
})

describe('loadSigningKeyFromEnv', () => {
    it('throws when the key is missing, regardless of NODE_ENV', () => {
        expect(() => loadSigningKeyFromEnv({})).toThrow(/must be set/)
        expect(() => loadSigningKeyFromEnv({ NODE_ENV: 'development' })).toThrow(/must be set/)
        expect(() => loadSigningKeyFromEnv({ NODE_ENV: 'production' })).toThrow(/must be set/)
        expect(() => loadSigningKeyFromEnv({ NODE_ENV: 'staging' })).toThrow(/must be set/)
    })

    it('throws when the key is shorter than 32 bytes', () => {
        expect(() => loadSigningKeyFromEnv({ MCP_SIGNED_STATE_KEY: 'short' })).toThrow(/must be set/)
        expect(() => loadSigningKeyFromEnv({ MCP_SIGNED_STATE_KEY: 'a'.repeat(31) })).toThrow(/must be set/)
    })

    it('returns the configured key when long enough', () => {
        const longKey = 'a'.repeat(32)
        const key = loadSigningKeyFromEnv({ MCP_SIGNED_STATE_KEY: longKey })
        expect(key.toString()).toBe(longKey)
    })
})

describe('NonceLedger', () => {
    function makeRedis(): { redis: { set: Mock<NonceLedgerRedis['set']> }; store: Map<string, string> } {
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
