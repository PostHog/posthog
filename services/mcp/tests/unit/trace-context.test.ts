import { describe, expect, it } from 'vitest'

import { childTraceparent, decideTraceSampling, mintTraceparent } from '@/lib/trace-context'

const W3C_TRACEPARENT = /^00-[0-9a-f]{32}-[0-9a-f]{16}-(00|01)$/

describe('mintTraceparent', () => {
    it('produces a W3C-formatted traceparent', () => {
        expect(mintTraceparent()).toMatch(W3C_TRACEPARENT)
    })

    it('mints distinct trace ids on successive calls', () => {
        const a = mintTraceparent()
        const b = mintTraceparent()
        expect(a).not.toBe(b)
        expect(a.split('-')[1]).not.toBe(b.split('-')[1])
    })

    it('forces sampled=01 when ratio is 1', () => {
        expect(mintTraceparent({ ratio: 1 }).endsWith('-01')).toBe(true)
    })

    it('forces sampled=00 when ratio is 0', () => {
        expect(mintTraceparent({ ratio: 0 }).endsWith('-00')).toBe(true)
    })

    it('makes the same sampling decision for the same conversation id', () => {
        const a = mintTraceparent({ mcpConversationId: 'conv-stable', ratio: 0.5 })
        const b = mintTraceparent({ mcpConversationId: 'conv-stable', ratio: 0.5 })
        expect(a.split('-')[3]).toBe(b.split('-')[3])
    })

    it('makes the same sampling decision for the same session id', () => {
        const a = mintTraceparent({ mcpSessionId: '0123456789abcdef0123456789abcdef', ratio: 0.5 })
        const b = mintTraceparent({ mcpSessionId: '0123456789abcdef0123456789abcdef', ratio: 0.5 })
        expect(a.split('-')[3]).toBe(b.split('-')[3])
    })

    it('prefers conversation id over session id for the sampling key', () => {
        // Pick two keys that hash to different sides of ratio=0.5: '00000000'
        // → 0 < 0.5 (sampled), 'ffffffff' → 1.0 ≥ 0.5 (not sampled).
        const conv = '00000000-conv'
        const sess = 'ffffffff-sess'
        const tp = mintTraceparent({ mcpConversationId: conv, mcpSessionId: sess, ratio: 0.5 })
        expect(tp.endsWith('-01')).toBe(true) // conversation wins → sampled
    })
})

describe('decideTraceSampling', () => {
    it('returns true when ratio >= 1, regardless of key', () => {
        expect(decideTraceSampling({ traceId: 'ffffffffffffffffffffffffffffffff', ratio: 1 })).toBe(true)
        expect(decideTraceSampling({ traceId: '00000000000000000000000000000000', ratio: 1.5 })).toBe(true)
    })

    it('returns false when ratio <= 0, regardless of key', () => {
        expect(decideTraceSampling({ traceId: '00000000000000000000000000000000', ratio: 0 })).toBe(false)
        expect(decideTraceSampling({ traceId: 'ffffffffffffffffffffffffffffffff', ratio: -1 })).toBe(false)
    })

    it.each([
        // Lowest hex prefix → always sampled at any ratio > 0
        ['00000000abcdef00', 0.01, true],
        // Highest hex prefix → never sampled below ratio=1
        ['ffffffffabcdef00', 0.99, false],
        // Mid prefix → boundary behaviour
        ['80000000abcdef00', 0.6, true],
        ['80000000abcdef00', 0.4, false],
    ])('uses the first 8 hex chars of the key to decide (key=%s, ratio=%s → %s)', (key, ratio, expected) => {
        expect(decideTraceSampling({ traceId: key, ratio })).toBe(expected)
    })

    it('falls back to false when the key prefix is not hex', () => {
        expect(decideTraceSampling({ traceId: 'not-hex!', ratio: 0.5 })).toBe(false)
    })

    it('defaults to a 10% ratio when none is provided', () => {
        // 0.0fffffff → ~6% of u32 space → comfortably below 10%
        expect(decideTraceSampling({ traceId: '0fffffff' + '0'.repeat(24) })).toBe(true)
        // 0x20000000 ≈ 12.5% — just above 10% threshold
        expect(decideTraceSampling({ traceId: '20000000' + '0'.repeat(24) })).toBe(false)
    })
})

describe('childTraceparent', () => {
    const parent = '00-0123456789abcdef0123456789abcdef-fedcba9876543210-01'

    it('preserves the parent trace id', () => {
        const child = childTraceparent(parent)
        expect(child.split('-')[1]).toBe('0123456789abcdef0123456789abcdef')
    })

    it('preserves the parent flags byte (does not force sampled)', () => {
        const unsampled = '00-0123456789abcdef0123456789abcdef-fedcba9876543210-00'
        expect(childTraceparent(unsampled).endsWith('-00')).toBe(true)
        expect(childTraceparent(parent).endsWith('-01')).toBe(true)
    })

    it('mints a fresh span id distinct from the parent', () => {
        const child = childTraceparent(parent)
        const childSpanId = child.split('-')[2]
        expect(childSpanId).toMatch(/^[0-9a-f]{16}$/)
        expect(childSpanId).not.toBe('fedcba9876543210')
    })

    it.each([
        ['empty', ''],
        ['wrong version', 'ff-0123456789abcdef0123456789abcdef-fedcba9876543210-01'],
        ['short trace id', '00-0123-fedcba9876543210-01'],
        ['short span id', '00-0123456789abcdef0123456789abcdef-fe-01'],
        ['short flags', '00-0123456789abcdef0123456789abcdef-fedcba9876543210-1'],
        ['three parts', '00-0123456789abcdef0123456789abcdef-fedcba9876543210'],
        ['garbage', 'not-a-traceparent'],
    ])('returns the input unchanged when %s', (_name, input) => {
        expect(childTraceparent(input)).toBe(input)
    })
})
