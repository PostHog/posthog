import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'

import type { FlagDefinitionsSnapshot, LocalFlagDefinition } from '@/lib/flag-cache'
import { computeHashBucket, evaluateFlagLocally } from '@/lib/local-flag-evaluation'

function snapshot(flags: LocalFlagDefinition[]): FlagDefinitionsSnapshot {
    return { etag: null, fetchedAt: Date.now(), flags }
}

describe('evaluateFlagLocally', () => {
    it('returns undefined when snapshot is null', async () => {
        expect(await evaluateFlagLocally(null, 'any', 'u1')).toBeUndefined()
    })

    it('returns undefined when flag missing from snapshot', async () => {
        expect(await evaluateFlagLocally(snapshot([]), 'missing', 'u1')).toBeUndefined()
    })

    it('returns false for a deleted flag', async () => {
        const snap = snapshot([{ key: 'f', active: true, deleted: true }])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(false)
    })

    it('returns false for an inactive flag', async () => {
        const snap = snapshot([{ key: 'f', active: false }])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(false)
    })

    it('returns false when no condition groups are defined', async () => {
        const snap = snapshot([{ key: 'f', active: true, filters: { groups: [] } }])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(false)
    })

    it('returns true for a 100% rollout group with no properties', async () => {
        const snap = snapshot([{ key: 'f', active: true, filters: { groups: [{ rollout_percentage: 100 }] } }])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(true)
    })

    it('returns true when rollout_percentage is missing (defaults to 100)', async () => {
        const snap = snapshot([{ key: 'f', active: true, filters: { groups: [{}] } }])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(true)
    })

    it('returns false for a 0% rollout group', async () => {
        const snap = snapshot([{ key: 'f', active: true, filters: { groups: [{ rollout_percentage: 0 }] } }])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(false)
    })

    it('OR-matches across multiple condition groups', async () => {
        // Use a property-filtered group (undecidable) OR'd with a 100% rollout group.
        // The 100% group matches, so flag is true even though the first is undecided.
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: {
                    groups: [
                        { rollout_percentage: 50, properties: [{ key: 'email', value: 'x' }] },
                        { rollout_percentage: 100 },
                    ],
                },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBe(true)
    })

    it('returns undefined when any group is undecided and no decided group matched', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: {
                    groups: [{ rollout_percentage: 0 }, { rollout_percentage: 50, properties: [{ key: 'email' }] }],
                },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('returns undefined for property-based targeting', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: { groups: [{ rollout_percentage: 100, properties: [{ key: 'email' }] }] },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('returns undefined for cohort filters', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: {
                    groups: [{ rollout_percentage: 100, properties: [{ type: 'cohort', key: 'id', value: 42 }] }],
                },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('returns undefined for group-aggregated flags', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: { aggregation_group_type_index: 0, groups: [{ rollout_percentage: 100 }] },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('returns undefined for multivariate flags', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: {
                    groups: [{ rollout_percentage: 100 }],
                    multivariate: { variants: [{ key: 'a', rollout_percentage: 50 }] },
                },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('returns undefined when experience continuity is enabled', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                ensure_experience_continuity: true,
                filters: { groups: [{ rollout_percentage: 100 }] },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('returns undefined when a variant override is set on the group', async () => {
        const snap = snapshot([
            {
                key: 'f',
                active: true,
                filters: { groups: [{ rollout_percentage: 100, variant: 'test' }] },
            },
        ])
        expect(await evaluateFlagLocally(snap, 'f', 'u1')).toBeUndefined()
    })

    it('bucketing is deterministic', async () => {
        const snap = snapshot([{ key: 'f', active: true, filters: { groups: [{ rollout_percentage: 30 }] } }])
        const a = await evaluateFlagLocally(snap, 'f', 'user-abc')
        const b = await evaluateFlagLocally(snap, 'f', 'user-abc')
        expect(a).toBe(b)
    })
})

describe('computeHashBucket', () => {
    /**
     * Reference implementation matching posthog-python / posthog-node exactly:
     * bucket = int(sha1(f"{key}.{uid}").hexdigest()[:15], 16) / 0xfffffffffffffff
     * Computed here with Node's crypto + BigInt to cross-check our Web Crypto impl.
     */
    function reference(flagKey: string, distinctId: string): number {
        const hex = createHash('sha1').update(`${flagKey}.${distinctId}`).digest('hex')
        const numerator = BigInt('0x' + hex.slice(0, 15))
        const denominator = BigInt('0xfffffffffffffff')
        return Number((numerator * 1_000_000_000_000n) / denominator) / 1_000_000_000_000
    }

    it.each([
        ['flag', 'user1'],
        ['mcp-version-2', 'abc-def-ghi'],
        ['another-flag', ''],
        ['f', '00000000-0000-0000-0000-000000000000'],
        ['with.dots.in.key', 'user.with.dots'],
        ['unicode', 'úser-ñame'],
    ])('matches node:crypto sha1 reference for (%s, %s)', async (flagKey, distinctId) => {
        const ours = await computeHashBucket(flagKey, distinctId)
        const expected = reference(flagKey, distinctId)
        // Allow a tiny delta (<1e-12) because we scale through BigInt/Number.
        expect(Math.abs(ours - expected)).toBeLessThan(1e-10)
    })

    it('is in [0, 1)', async () => {
        const buckets: number[] = []
        for (let i = 0; i < 50; i++) {
            buckets.push(await computeHashBucket('k', `u${i}`))
        }
        expect(Math.min(...buckets)).toBeGreaterThanOrEqual(0)
        expect(Math.max(...buckets)).toBeLessThan(1)
    })

    it('is approximately uniform across 1000 samples', async () => {
        const samples: number[] = []
        for (let i = 0; i < 1000; i++) {
            samples.push(await computeHashBucket('uniform-test', `user-${i}`))
        }
        const mean = samples.reduce((a, b) => a + b, 0) / samples.length
        // Mean of uniform [0,1) is 0.5; 1000 samples gives stderr ≈ 0.009, so ±0.05 is comfortable.
        expect(mean).toBeGreaterThan(0.45)
        expect(mean).toBeLessThan(0.55)
    })
})
