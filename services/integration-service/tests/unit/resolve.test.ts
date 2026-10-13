import { describe, expect, it } from 'vitest'

import { register, resolveTotal } from '@/metrics'
import { resolveKeys } from '@/resolve'
import type { CallerIdentity, MountedSecrets } from '@/types'

function mounted(secrets: MountedSecrets['secrets']): MountedSecrets {
    return { fetchedAt: '2026-08-06T00:00:00.000Z', versionId: 'v1', secrets }
}

const MOUNTED = mounted({
    GOOGLE_ADS_APP_CLIENT_ID: { state: 'steady', value: 'ga-id', versionId: 'v1', fetchedAt: 'now' },
    GOOGLE_ADS_APP_CLIENT_SECRET: {
        state: 'rotating',
        value: 'ga-live',
        incoming: 'ga-staged',
        versionId: 'v1',
        fetchedAt: 'now',
    },
    STRIPE_APP_SECRET_KEY: { state: 'steady', value: 'sk-live', versionId: 'v1', fetchedAt: 'now' },
})

function identity(requestedKeys: string[]): CallerIdentity {
    return { deployment: 'temporal-worker-data-warehouse', caller: 'warehouse-sources', requestedKeys }
}

describe('resolve', () => {
    // There is no per-deployment allowlist: any authenticated deployment may read anything
    // on the mount. Containment is revoking that deployment's signing key, not a list
    // somebody has to keep current.
    it('serves anything on the mount to an authenticated deployment', async () => {
        const response = resolveKeys(identity(['GOOGLE_ADS_APP_CLIENT_ID', 'STRIPE_APP_SECRET_KEY']), MOUNTED)

        expect(Object.keys(response.secrets).sort()).toEqual(['GOOGLE_ADS_APP_CLIENT_ID', 'STRIPE_APP_SECRET_KEY'])
        expect(response.missing).toEqual([])
    })

    it('serves the requested fields with their rotation state', async () => {
        const response = resolveKeys(identity(['GOOGLE_ADS_APP_CLIENT_ID', 'GOOGLE_ADS_APP_CLIENT_SECRET']), MOUNTED)

        expect(response.secrets['GOOGLE_ADS_APP_CLIENT_ID']).toMatchObject({ state: 'steady', value: 'ga-id' })
        // `previous` is the wire name; it carries the staged (incoming) value. The mismatch is
        // deliberate and documented on WireSecret — the boundary lags the internal rename.
        expect(response.secrets['GOOGLE_ADS_APP_CLIENT_SECRET']).toMatchObject({
            state: 'rotating',
            value: 'ga-live',
            previous: 'ga-staged',
        })
    })

    // THE containment property at this layer: the scope is the identity's key list and
    // nothing else. The route-level half — a request body cannot widen it — is pinned in
    // app.test.ts, since this function never sees an HTTP request.
    it('serves nothing outside the token scope even though the caller may read it', async () => {
        const response = resolveKeys(identity(['GOOGLE_ADS_APP_CLIENT_ID']), MOUNTED)

        expect(Object.keys(response.secrets)).toEqual(['GOOGLE_ADS_APP_CLIENT_ID'])
        expect(response.secrets).not.toHaveProperty('STRIPE_APP_SECRET_KEY')
    })

    it.each([
        ['a name nothing on the mount carries', 'NOT_A_REAL_KEY'],
        // The mount never puts a reserved entry in the secret set, so a token naming a
        // signing key gets the same answer as a token naming nonsense.
        ['a reserved entry a token asked for by name', '__CALLER_KEY_POSTHOG_DJANGO'],
    ])('reports %s as missing rather than failing the request', async (_label, key) => {
        const response = resolveKeys(identity([key, 'GOOGLE_ADS_APP_CLIENT_ID']), MOUNTED)

        expect(response.missing).toContain(key)
        expect(response.secrets).not.toHaveProperty(key)
        expect(response.secrets).toHaveProperty('GOOGLE_ADS_APP_CLIENT_ID')
    })

    it('serves a recovery field with no value so the caller fails fast', async () => {
        const response = resolveKeys(
            identity(['STRIPE_APP_SECRET_KEY']),
            mounted({ STRIPE_APP_SECRET_KEY: { state: 'recovery', versionId: 'v1', fetchedAt: 'now' } })
        )

        expect(response.secrets['STRIPE_APP_SECRET_KEY']).toMatchObject({ state: 'recovery' })
        expect(response.secrets['STRIPE_APP_SECRET_KEY']?.value).toBeUndefined()
    })

    // prom-client keeps every series in process memory for the lifetime of the pod, so a
    // caller holding a signing key could otherwise grow the heap and the scrape payload
    // without bound. Nothing a caller types may become a label: not an invented key name,
    // and not the `caller` claim.
    it('never puts caller-supplied text on a metric label', async () => {
        register.resetMetrics()
        const invented = 'TOTALLY_MADE_UP_KEY_NAME_9f2a'
        const claimedCaller = 'a-product-nobody-registered-4b81'

        const response = resolveKeys(
            { deployment: 'posthog-django', caller: claimedCaller, requestedKeys: [invented] },
            MOUNTED
        )

        const labelValues = (await resolveTotal.get()).values.flatMap((v) => Object.values(v.labels).map(String))
        expect(labelValues).not.toContain(invented)
        expect(labelValues).not.toContain(claimedCaller)
        // The real name still reaches the caller, just not the metric.
        expect(response.missing).toContain(invented)
    })
})
