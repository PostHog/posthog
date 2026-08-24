import { SignJWT } from 'jose'
import { beforeEach, describe, expect, it } from 'vitest'

import { JwtVerifier } from '@/auth/jwt'
import type { SigningKeyLoader } from '@/auth/registry'
import { AUDIENCE, type SigningKeys } from '@/auth/types'
import { createApp } from '@/http/app'
import { httpRequestsTotal, register } from '@/metrics'
import type { Lifecycle, MountedSecrets } from '@/types'

const RESOLVE_PATH = '/v1/secrets/resolve'

const DEPLOYMENT = 'temporal-worker-data-warehouse'
const SIGNING_KEY = 'a-signing-key'
const KEYS: SigningKeys = { [DEPLOYMENT]: [SIGNING_KEY] }
const KEY = 'HUBSPOT_APP_CLIENT_SECRET'

const MOUNTED: MountedSecrets = {
    fetchedAt: '2026-08-06T00:00:00.000Z',
    versionId: 'v1',
    secrets: { [KEY]: { state: 'steady', value: 'hunter2-zx9q', versionId: 'v1', fetchedAt: 'now' } },
}

async function mint(
    opts: { key?: string; keys?: string[]; expiresIn?: string; audience?: string } = {}
): Promise<string> {
    return new SignJWT({ caller: 'warehouse-sources', keys: opts.keys ?? [KEY] })
        .setProtectedHeader({ alg: 'HS256' })
        .setAudience(opts.audience ?? AUDIENCE)
        .setIssuedAt()
        .setExpirationTime(opts.expiresIn ?? '5m')
        .sign(new TextEncoder().encode(opts.key ?? SIGNING_KEY))
}

function build(
    overrides: {
        lifecycle?: Partial<Lifecycle>
        secrets?: () => MountedSecrets | null
    } = {}
): { app: ReturnType<typeof createApp>; lifecycle: Lifecycle } {
    const lifecycle: Lifecycle = { shuttingDown: false, ready: true, ...overrides.lifecycle }
    const app = createApp({
        verifier: new JwtVerifier({ entries: () => Object.entries(KEYS) } as SigningKeyLoader),
        lifecycle,
        secrets: overrides.secrets ?? ((): MountedSecrets | null => MOUNTED),
    })
    return { app, lifecycle }
}

const authed = async (token?: string): Promise<Request> =>
    new Request(`http://svc${RESOLVE_PATH}`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
    })

describe('http surface', () => {
    beforeEach(() => {
        register.resetMetrics()
    })

    describe('resolve', () => {
        it('serves the requested secret to a valid token', async () => {
            const { app } = build()
            const res = await app.request(await authed(await mint()))

            expect(res.status).toBe(200)
            await expect(res.json()).resolves.toMatchObject({ secrets: { [KEY]: { value: 'hunter2-zx9q' } } })
        })

        // Every rejection is a flat 401 with no detail: the reason is a metric label and a
        // log line, not something an unauthenticated caller gets to enumerate.
        it.each([
            ['no Authorization header', undefined],
            ['a garbage token', 'not-a-jwt'],
            ['a token signed with an unknown key', 'wrong-key'],
            ['an expired token', 'expired'],
            ['a token for another audience', 'audience'],
        ])('rejects %s with 401 and no detail', async (_label, kind) => {
            let token: string | undefined
            if (kind === 'not-a-jwt') {
                token = 'not-a-jwt'
            } else if (kind === 'wrong-key') {
                token = await mint({ key: 'nobody-lists-this' })
            } else if (kind === 'expired') {
                token = await mint({ expiresIn: '-1s' })
            } else if (kind === 'audience') {
                token = await mint({ audience: 'posthog:recording_api' })
            }

            const res = await build().app.request(await authed(token))

            expect(res.status).toBe(401)
            await expect(res.json()).resolves.toEqual({ error: 'Unauthorized' })
        })

        // A pod that holds no secrets must not answer all-missing: callers treat a
        // missing key as terminal, so an empty answer would look like a deleted secret
        // rather than an unavailable service.
        it('answers 503 rather than all-missing when it holds no secrets', async () => {
            const { app } = build({ secrets: () => null })
            const res = await app.request(await authed(await mint()))

            expect(res.status).toBe(503)
        })

        it('never returns a secret value on a rejected request', async () => {
            const res = await build().app.request(await authed('not-a-jwt'))
            expect(await res.text()).not.toContain('hunter2-zx9q')
        })
    })

    describe('probes', () => {
        it('reports liveness regardless of readiness', async () => {
            const { app } = build({ lifecycle: { ready: false } })
            expect((await app.request('http://svc/_liveness')).status).toBe(200)
        })

        it.each([
            ['starting', { ready: false, shuttingDown: false }, 503],
            ['ready', { ready: true, shuttingDown: false }, 200],
            ['shutting down', { ready: true, shuttingDown: true }, 503],
        ])('reports %s as %i', async (_label, lifecycle, status) => {
            const { app } = build({ lifecycle })
            expect((await app.request('http://svc/_readiness')).status).toBe(status)
        })

        // Draining has to win over readiness, or Kubernetes keeps routing to a pod that is
        // already closing its listener.
        it('reports not-ready while shutting down even though a snapshot is held', async () => {
            const { app, lifecycle } = build()
            expect((await app.request('http://svc/_readiness')).status).toBe(200)

            lifecycle.shuttingDown = true
            expect((await app.request('http://svc/_readiness')).status).toBe(503)
        })
    })

    // The request scope is the token, full stop. A route change that read a body and
    // merged its key names into the scope would fail here, not in resolve.test.ts, because
    // resolveKeys never sees the HTTP request.
    it('ignores a request body naming keys outside the token scope', async () => {
        const { app } = build()
        const res = await app.request(
            new Request('http://svc/v1/secrets/resolve', {
                method: 'POST',
                headers: { Authorization: `Bearer ${await mint()}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({ keys: ['STRIPE_APP_SECRET_KEY'] }),
            })
        )

        expect(res.status).toBe(200)
        const body = (await res.json()) as { secrets: Record<string, unknown> }
        expect(Object.keys(body.secrets)).toEqual([KEY])
    })

    it('never exposes a secret value in the scrape', async () => {
        const { app } = build()
        await app.request(await authed(await mint()))

        expect(await register.metrics()).not.toContain('hunter2-zx9q')
    })

    // An unmatched path must not become a label value, or anyone can grow the series set
    // by requesting random URLs.
    it('collapses every unknown route to one constant metric label', async () => {
        const { app } = build()
        await app.request('http://svc/definitely-not-a-route-9f2a')
        await app.request('http://svc/another-invented-route-c81d')

        const labels = (await httpRequestsTotal.get()).values.map((v) => String(v.labels['route']))
        expect(labels).not.toContain('/definitely-not-a-route-9f2a')
        expect(labels).not.toContain('/another-invented-route-c81d')
        expect(new Set(labels).size).toBe(1)
    })
})
