import { describe, expect, it, vi } from 'vitest'

import { register, resolveTotal } from '@/metrics.js'
import { resolveKeys, type ResolveDeps } from '@/policy/resolve.js'
import type { CallerIdentity, ProviderSnapshot } from '@/types.js'
import type { UsageRecorder } from '@/usage/recorder.js'

function snapshot(provider: string, secrets: ProviderSnapshot['secrets']): ProviderSnapshot {
    return {
        provider,
        fetchedAt: '2026-08-06T00:00:00.000Z',
        versionId: 'v1',
        currentActivatedAt: '2026-01-01T00:00:00.000Z',
        secrets,
    }
}

const SNAPSHOTS: Record<string, ProviderSnapshot> = {
    'google-ads': snapshot('google-ads', {
        GOOGLE_ADS_APP_CLIENT_ID: { state: 'steady', value: 'ga-id', versionId: 'v1', fetchedAt: 'now' },
        GOOGLE_ADS_APP_CLIENT_SECRET: {
            state: 'rotating',
            value: 'ga-new',
            previous: 'ga-old',
            versionId: 'v1',
            fetchedAt: 'now',
        },
    }),
    stripe: snapshot('stripe', {
        STRIPE_APP_SECRET_KEY: { state: 'steady', value: 'sk-live', versionId: 'v1', fetchedAt: 'now' },
    }),
}

function deps(overrides: Partial<ResolveDeps> = {}): ResolveDeps {
    return {
        loadProvider: (provider) => Promise.resolve(SNAPSHOTS[provider] ?? null),
        recorder: { record: vi.fn() } as unknown as UsageRecorder,
        maxAgeSeconds: 60,
        ...overrides,
    }
}

function identity(requestedKeys: string[], allowed: string[] = ['google-ads', 'stripe']): CallerIdentity {
    return {
        caller: 'temporal-worker-data-warehouse',
        allowedProviders: new Set(allowed),
        requestedKeys,
    }
}

describe('resolve', () => {
    it('serves the requested fields with their rotation state', async () => {
        const response = await resolveKeys(
            identity(['GOOGLE_ADS_APP_CLIENT_ID', 'GOOGLE_ADS_APP_CLIENT_SECRET']),
            [],
            deps()
        )

        expect(response.secrets['GOOGLE_ADS_APP_CLIENT_ID']).toMatchObject({ state: 'steady', value: 'ga-id' })
        expect(response.secrets['GOOGLE_ADS_APP_CLIENT_SECRET']).toMatchObject({
            state: 'rotating',
            value: 'ga-new',
            previous: 'ga-old',
        })
        expect(response.max_age_seconds).toBe(60)
    })

    // THE containment property. The caller is allowed Stripe, but this token did not ask
    // for it — so a token lifted from a log unlocks one provider, not the caller's whole
    // entitlement. If someone reintroduces a request body, this is the test that fails.
    it('serves nothing outside the token scope even when the caller is allowed that provider', async () => {
        const response = await resolveKeys(identity(['GOOGLE_ADS_APP_CLIENT_ID']), [], deps())

        expect(Object.keys(response.secrets)).toEqual(['GOOGLE_ADS_APP_CLIENT_ID'])
        expect(response.secrets).not.toHaveProperty('STRIPE_APP_SECRET_KEY')
    })

    // A policy mistake should read as one named field, not an opaque 403 over the batch.
    it('reports a key outside the allowlist as denied while still serving the permitted ones', async () => {
        const response = await resolveKeys(
            identity(['GOOGLE_ADS_APP_CLIENT_ID', 'STRIPE_APP_SECRET_KEY'], ['google-ads']),
            [],
            deps()
        )

        expect(response.denied).toEqual(['STRIPE_APP_SECRET_KEY'])
        expect(response.secrets).not.toHaveProperty('STRIPE_APP_SECRET_KEY')
        expect(response.secrets).toHaveProperty('GOOGLE_ADS_APP_CLIENT_ID')
    })

    it.each([
        ['a key absent from the provider manifest', 'NOT_A_REAL_KEY'],
        ['a manifest key with no value in the store', 'STRIPE_SIGNING_SECRET'],
    ])('reports %s as missing rather than failing the request', async (_label, key) => {
        const response = await resolveKeys(identity([key, 'GOOGLE_ADS_APP_CLIENT_ID']), [], deps())

        expect(response.missing).toContain(key)
        expect(response.secrets).toHaveProperty('GOOGLE_ADS_APP_CLIENT_ID')
    })

    it('serves a recovery field with no value so the caller fails fast', async () => {
        const response = await resolveKeys(identity(['STRIPE_APP_SECRET_KEY']), [], {
            ...deps(),
            loadProvider: () =>
                Promise.resolve(
                    snapshot('stripe', {
                        STRIPE_APP_SECRET_KEY: { state: 'recovery', versionId: 'v1', fetchedAt: 'now' },
                    })
                ),
        })

        expect(response.secrets['STRIPE_APP_SECRET_KEY']).toMatchObject({ state: 'recovery' })
        expect(response.secrets['STRIPE_APP_SECRET_KEY']?.value).toBeUndefined()
    })

    it('loads each provider once even when several of its fields are requested', async () => {
        const loadProvider = vi.fn((provider: string) => Promise.resolve(SNAPSHOTS[provider] ?? null))
        await resolveKeys(
            identity(['GOOGLE_ADS_APP_CLIENT_ID', 'GOOGLE_ADS_APP_CLIENT_SECRET', 'STRIPE_APP_SECRET_KEY']),
            [],
            deps({ loadProvider })
        )

        expect(loadProvider).toHaveBeenCalledTimes(2)
    })

    // A key name a caller invents must never reach a Prometheus label. prom-client keeps
    // every series in process memory for the lifetime of the pod, so a caller holding a
    // signing key could otherwise grow the heap and the scrape payload without bound.
    it('never puts a caller-supplied key name on a metric label', async () => {
        register.resetMetrics()
        const invented = 'TOTALLY_MADE_UP_KEY_NAME_9f2a'

        const response = await resolveKeys(identity([invented]), [], deps())

        const series = await resolveTotal.get()
        const labelValues = series.values.flatMap((v) => Object.values(v.labels).map(String))
        expect(labelValues).not.toContain(invented)
        // The real name still reaches the caller, just not the metric.
        expect(response.missing).toContain(invented)
    })

    it('drops an unknown key from the previous-used report before it reaches Redis', async () => {
        const record = vi.fn()
        await resolveKeys(
            identity(['GOOGLE_ADS_APP_CLIENT_ID', 'MADE_UP_KEY']),
            ['GOOGLE_ADS_APP_CLIENT_ID', 'MADE_UP_KEY'],
            deps({ recorder: { record } as unknown as UsageRecorder })
        )

        expect(record).toHaveBeenCalledWith(
            'temporal-worker-data-warehouse',
            ['GOOGLE_ADS_APP_CLIENT_ID'],
            ['GOOGLE_ADS_APP_CLIENT_ID']
        )
    })

    it('records only successfully served keys against the caller usage rollup', async () => {
        const record = vi.fn()
        await resolveKeys(
            identity(['GOOGLE_ADS_APP_CLIENT_ID', 'NOT_A_REAL_KEY']),
            ['GOOGLE_ADS_APP_CLIENT_SECRET'],
            deps({ recorder: { record } as unknown as UsageRecorder })
        )

        expect(record).toHaveBeenCalledWith(
            'temporal-worker-data-warehouse',
            ['GOOGLE_ADS_APP_CLIENT_ID'],
            ['GOOGLE_ADS_APP_CLIENT_SECRET']
        )
    })
})
