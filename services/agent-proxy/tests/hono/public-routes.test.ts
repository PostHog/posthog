import { Hono } from 'hono'
import { describe, expect, it } from 'vitest'

import { registerPublicRoutes } from '@/hono/public-routes.js'

function makeApp(metricsToken: string): Hono {
    const app = new Hono()
    registerPublicRoutes(app, { shuttingDown: false }, metricsToken)
    return app
}

describe('public routes', () => {
    describe('/_metrics token guard', () => {
        it('serves metrics openly when no token is configured', async () => {
            const res = await makeApp('').request('/_metrics')

            expect(res.status).toBe(200)
            expect(res.headers.get('Content-Type')).toContain('text/plain')
        })

        it('rejects a scrape without a bearer token when a token is configured', async () => {
            const res = await makeApp('scrape-secret').request('/_metrics')

            expect(res.status).toBe(401)
        })

        it('rejects a scrape with the wrong bearer token', async () => {
            const res = await makeApp('scrape-secret').request('/_metrics', {
                headers: { Authorization: 'Bearer not-the-secret' },
            })

            expect(res.status).toBe(401)
        })

        it('serves metrics with the correct bearer token', async () => {
            const res = await makeApp('scrape-secret').request('/_metrics', {
                headers: { Authorization: 'Bearer scrape-secret' },
            })

            expect(res.status).toBe(200)
        })
    })

    it('health and readiness routes stay open regardless of the metrics token', async () => {
        const app = makeApp('scrape-secret')

        expect((await app.request('/_health')).status).toBe(200)
        expect((await app.request('/_readyz')).status).toBe(200)
        expect((await app.request('/health')).status).toBe(200)
    })
})
