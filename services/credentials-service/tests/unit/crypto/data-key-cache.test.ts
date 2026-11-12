import { describe, expect, it } from 'vitest'

import { DataKeyCache } from '@/crypto/data-key-cache'

function wrapped(n: number): Buffer {
    return Buffer.from(`wrapped-${n}`)
}

function plaintext(n: number): Buffer {
    return Buffer.alloc(32, n)
}

const ZERO = Buffer.alloc(32)

describe('DataKeyCache', () => {
    it('evicts the least recently used key past the limit and zeroes it', () => {
        const cache = new DataKeyCache({ maxEntries: 2, ttlMs: 60_000 })
        const keys = [plaintext(1), plaintext(2), plaintext(3)]
        cache.set(wrapped(1), keys[0] as Buffer)
        cache.set(wrapped(2), keys[1] as Buffer)
        // A read makes key 1 the most recently used, so key 2 goes first.
        cache.get(wrapped(1))

        cache.set(wrapped(3), keys[2] as Buffer)

        expect(cache.size).toBe(2)
        expect(cache.get(wrapped(2))).toBeUndefined()
        expect(keys[1]).toEqual(ZERO)
        expect(cache.get(wrapped(1))).toEqual(plaintext(1))
        expect(cache.get(wrapped(3))).toEqual(plaintext(3))
    })

    it.each([
        ['just before the TTL', 59_999, true],
        ['at the TTL', 60_000, false],
    ])('a key read %s is %s', (_label, elapsed, cached) => {
        let now = 0
        const cache = new DataKeyCache({ maxEntries: 10, ttlMs: 60_000, now: () => now })
        const key = plaintext(7)
        cache.set(wrapped(7), key)

        now = elapsed
        const hit = cache.get(wrapped(7))

        if (cached) {
            expect(hit).toEqual(plaintext(7))
        } else {
            expect(hit).toBeUndefined()
            expect(key).toEqual(ZERO)
            expect(cache.size).toBe(0)
        }
    })

    it('zeroes expired keys that nobody reads on a later write', () => {
        let now = 0
        const cache = new DataKeyCache({ maxEntries: 10, ttlMs: 60_000, now: () => now })
        const idle = plaintext(1)
        cache.set(wrapped(1), idle)

        now = 120_000
        cache.set(wrapped(2), plaintext(2))

        expect(idle).toEqual(ZERO)
        expect(cache.size).toBe(1)
    })

    it('zeroes the previous key when a wrapped key is set again', () => {
        const cache = new DataKeyCache({ maxEntries: 10, ttlMs: 60_000 })
        const first = plaintext(1)
        cache.set(wrapped(1), first)

        cache.set(wrapped(1), plaintext(9))

        expect(first).toEqual(ZERO)
        expect(cache.get(wrapped(1))).toEqual(plaintext(9))
    })

    it('zeroes every key on clear', () => {
        const cache = new DataKeyCache({ maxEntries: 10, ttlMs: 60_000 })
        const keys = [plaintext(1), plaintext(2)]
        keys.forEach((key, i) => cache.set(wrapped(i), key))

        cache.clear()

        expect(keys).toEqual([ZERO, ZERO])
        expect(cache.size).toBe(0)
    })
})
