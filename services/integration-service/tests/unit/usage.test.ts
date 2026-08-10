import { describe, expect, it } from 'vitest'

import type { SecretsSnapshot } from '@/types.js'
import { buildUsageMap, type UsageMap } from '@/usage/publisher.js'

const ACTIVATED_AT = '2026-08-01T00:00:00.000Z'
const BEFORE = Date.parse('2026-07-30T00:00:00.000Z')
const AFTER = Date.parse('2026-08-02T00:00:00.000Z')

const ROTATING: SecretsSnapshot = {
    fetchedAt: '2026-08-06T00:00:00.000Z',
    versionId: 'v-new',
    changedAt: ACTIVATED_AT,
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
    snapshot?: SecretsSnapshot | null
    reads?: Record<string, number>
    lastSeen?: Record<string, number>
}): UsageMap {
    return buildUsageMap({
        env: 'prod-us',
        generatedAt: '2026-08-06T12:00:00.000Z',
        quietWindowHours: 24,
        snapshot: opts.snapshot === undefined ? ROTATING : opts.snapshot,
        reads: new Map(Object.entries(opts.reads ?? {})),
        lastSeen: new Map(Object.entries(opts.lastSeen ?? {})),
    })
}

const KEY = 'GOOGLE_ADS_APP_CLIENT_SECRET'
const WORKER = 'temporal-worker-data-warehouse'
const DJANGO = 'posthog-django'

describe('usage map', () => {
    it('attributes reads to the deployment that made them', () => {
        const usage = build({ reads: { [`${KEY}|${WORKER}`]: 42 } })
        expect(usage.keys[KEY]?.callers[0]).toMatchObject({ caller: WORKER, reads24h: 42 })
    })

    it('carries the rotation state and current version through', () => {
        const usage = build({ reads: { [`${KEY}|${WORKER}`]: 1 } })
        expect(usage.keys[KEY]).toMatchObject({
            provider: 'google-ads',
            state: 'rotating',
            currentVersionId: 'v-new',
            currentActivatedAt: ACTIVATED_AT,
        })
    })

    // Sound only because callers do not cache: a read after activation necessarily
    // returned the new value, so "read since" means "using the new value".
    describe('safeToRetirePrevious', () => {
        it('is true when every reader has read since the new value was activated', () => {
            const usage = build({
                reads: { [`${KEY}|${WORKER}`]: 100, [`${KEY}|${DJANGO}`]: 5 },
                lastSeen: { [`${KEY}|${WORKER}`]: AFTER, [`${KEY}|${DJANGO}`]: AFTER },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(true)
        })

        // The trap: with nothing reading the credential, "no reader is still on the old
        // value" is vacuously true, and retiring would look safe when it is not.
        it('is false when nothing reads the credential at all', () => {
            expect(build({}).keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        it('is false while a reader has not come back since activation', () => {
            const usage = build({
                reads: { [`${KEY}|${WORKER}`]: 100 },
                lastSeen: { [`${KEY}|${WORKER}`]: BEFORE },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        it('is false when one deployment has moved on but another has not', () => {
            const usage = build({
                reads: { [`${KEY}|${WORKER}`]: 100, [`${KEY}|${DJANGO}`]: 5 },
                lastSeen: { [`${KEY}|${WORKER}`]: AFTER, [`${KEY}|${DJANGO}`]: BEFORE },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        // The dormant-consumer trap: a deployment that reads this key less often than the
        // rolling window has no entry in `reads`, only a last-seen record. If the verdict
        // were built from `reads` alone, one active caller reading once after activation
        // would declare the previous value retirable while that consumer is still on it.
        it('is false while a caller seen only outside the rolling window predates activation', () => {
            const usage = build({
                reads: { [`${KEY}|${WORKER}`]: 100 },
                lastSeen: { [`${KEY}|${WORKER}`]: AFTER, [`${KEY}|${DJANGO}`]: BEFORE },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
            expect(usage.keys[KEY]?.callers).toContainEqual({
                caller: DJANGO,
                reads24h: 0,
                lastSeen: new Date(BEFORE).toISOString(),
                onCurrentValue: false,
            })
        })

        it('is true when a caller seen only outside the rolling window has moved on', () => {
            const usage = build({
                reads: { [`${KEY}|${WORKER}`]: 100 },
                lastSeen: { [`${KEY}|${WORKER}`]: AFTER, [`${KEY}|${DJANGO}`]: AFTER },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(true)
        })

        it('is false for a key that is not mid-rotation, since there is nothing to retire', () => {
            const steady: SecretsSnapshot = {
                ...ROTATING,
                secrets: { [KEY]: { state: 'steady', value: 'only', versionId: 'v-new', fetchedAt: 'now' } },
            }
            const usage = build({
                snapshot: steady,
                reads: { [`${KEY}|${WORKER}`]: 100 },
                lastSeen: { [`${KEY}|${WORKER}`]: AFTER },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })

        it('is false when the current version has no activation time to compare against', () => {
            const undated: SecretsSnapshot = { ...ROTATING, changedAt: null }
            const usage = build({
                snapshot: undated,
                reads: { [`${KEY}|${WORKER}`]: 100 },
                lastSeen: { [`${KEY}|${WORKER}`]: AFTER },
            })
            expect(usage.keys[KEY]?.safeToRetirePrevious).toBe(false)
        })
    })

    // The artifact lands in an S3 bucket the secrets UI reads. It carries topology only.
    it('contains no credential values once serialized', () => {
        const serialized = JSON.stringify(
            build({ reads: { [`${KEY}|${WORKER}`]: 5 }, lastSeen: { [`${KEY}|${WORKER}`]: AFTER } })
        )

        expect(serialized).not.toContain('ga-new-super-secret')
        expect(serialized).not.toContain('ga-old-super-secret')
        expect(serialized).toContain(KEY)
        expect(serialized).toContain(WORKER)
    })

    it('records last-seen for deployments that have read the key', () => {
        const usage = build({ reads: { [`${KEY}|${WORKER}`]: 5 }, lastSeen: { [`${KEY}|${WORKER}`]: AFTER } })
        expect(usage.keys[KEY]?.callers[0]?.lastSeen).toBe(new Date(AFTER).toISOString())
    })
})
