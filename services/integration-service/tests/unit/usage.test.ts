import { describe, expect, it } from 'vitest'

import type { ProviderSnapshot } from '@/types.js'
import { buildUsageMap } from '@/usage/publisher.js'

const ROTATING: ProviderSnapshot = {
    provider: 'google-ads',
    fetchedAt: '2026-08-06T00:00:00.000Z',
    versionId: 'v-new',
    currentActivatedAt: '2026-08-01T00:00:00.000Z',
    secrets: {
        GOOGLE_ADS_APP_CLIENT_SECRET: {
            state: 'rotating',
            value: 'ga-new-super-secret',
            previous: 'ga-old-super-secret',
            versionId: 'v-new',
            fetchedAt: '2026-08-06T00:00:00.000Z',
        },
    },
}

function build(opts: {
    snapshots?: ProviderSnapshot[]
    reads?: Record<string, number>
    previousUsed?: Record<string, number>
    lastSeen?: Record<string, number>
}) {
    return buildUsageMap({
        env: 'prod-us',
        generatedAt: '2026-08-06T12:00:00.000Z',
        quietWindowHours: 24,
        snapshots: opts.snapshots ?? [ROTATING],
        reads: new Map(Object.entries(opts.reads ?? {})),
        previousUsed: new Map(Object.entries(opts.previousUsed ?? {})),
        lastSeen: new Map(Object.entries(opts.lastSeen ?? {})),
    })
}

const KEY = 'GOOGLE_ADS_APP_CLIENT_SECRET'
const CALLER = 'temporal-worker-data-warehouse'

describe('usage map', () => {
    it('attributes reads to the caller that made them', () => {
        const usage = build({ reads: { [`${KEY}|${CALLER}`]: 42 } })
        expect(usage.keys[KEY]?.callers).toEqual([{ caller: CALLER, reads24h: 42, previousUsed24h: 0, lastSeen: null }])
    })

    it('carries the rotation state and current version through', () => {
        const usage = build({ reads: { [`${KEY}|${CALLER}`]: 1 } })
        expect(usage.keys[KEY]).toMatchObject({
            provider: 'google-ads',
            state: 'rotating',
            currentVersionId: 'v-new',
            currentActivatedAt: '2026-08-01T00:00:00.000Z',
        })
    })

    describe('safeToRetirePrevious', () => {
        it('is true when nobody needed the previous value and the current one is being read', () => {
            const usage = build({ reads: { [`${KEY}|${CALLER}`]: 100 } })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(true)
        })

        // The trap the two-condition rule exists for. Zero previous-value use looks
        // identical whether the rotation has landed everywhere or nothing is reading the
        // credential at all — and only one of those is safe to act on.
        it('is false when nothing is reading the credential at all', () => {
            const usage = build({ reads: {}, previousUsed: {} })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        it('is false while any caller still needs the previous value', () => {
            const usage = build({
                reads: { [`${KEY}|${CALLER}`]: 100 },
                previousUsed: { [`${KEY}|${CALLER}`]: 1 },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        it('is false when one caller has migrated but another has not', () => {
            const usage = build({
                reads: { [`${KEY}|${CALLER}`]: 100, [`${KEY}|posthog-django`]: 5 },
                previousUsed: { [`${KEY}|posthog-django`]: 3 },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        it('is false for a key that is not mid-rotation, since there is nothing to retire', () => {
            const steady: ProviderSnapshot = {
                ...ROTATING,
                secrets: {
                    [KEY]: { state: 'steady', value: 'ga-only', versionId: 'v-new', fetchedAt: 'now' },
                },
            }
            const usage = build({ snapshots: [steady], reads: { [`${KEY}|${CALLER}`]: 100 } })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })
    })

    // The artifact lands in an S3 bucket the secrets UI reads. It carries topology, and
    // topology only.
    it('contains no credential values once serialized', () => {
        const serialized = JSON.stringify(
            build({
                reads: { [`${KEY}|${CALLER}`]: 5 },
                previousUsed: { [`${KEY}|${CALLER}`]: 1 },
                lastSeen: { [`${KEY}|${CALLER}`]: Date.parse('2026-08-06T11:00:00.000Z') },
            })
        )

        expect(serialized).not.toContain('ga-new-super-secret')
        expect(serialized).not.toContain('ga-old-super-secret')
        expect(serialized).toContain(KEY)
        expect(serialized).toContain(CALLER)
    })

    it('records last-seen for callers that have read the key', () => {
        const usage = build({
            reads: { [`${KEY}|${CALLER}`]: 5 },
            lastSeen: { [`${KEY}|${CALLER}`]: Date.parse('2026-08-06T11:00:00.000Z') },
        })
        expect(usage.keys[KEY]?.callers[0]?.lastSeen).toBe('2026-08-06T11:00:00.000Z')
    })
})
