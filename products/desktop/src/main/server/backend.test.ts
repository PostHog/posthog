import * as assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as http from 'node:http'
import * as os from 'node:os'
import * as path from 'node:path'
import { after, before, beforeEach, describe, test } from 'node:test'

import { isProxyPath, type LocalBackend, startLocalBackend, type UpstreamAuth } from './backend.ts'

interface UpstreamRequest {
    method: string
    url: string
    headers: http.IncomingHttpHeaders
    body: string
}

describe('local backend', () => {
    let tmpDir: string
    let distDir: string
    let cacheDir: string
    let upstream: http.Server
    let upstreamOrigin: string
    let upstreamRequests: UpstreamRequest[]
    let backend: LocalBackend
    let auth: UpstreamAuth | null
    let signOutRequests: number
    let authRejections: number

    before(async () => {
        tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'posthog-desktop-test-'))
        distDir = path.join(tmpDir, 'dist')
        cacheDir = path.join(tmpDir, 'cache')
        fs.mkdirSync(distDir, { recursive: true })
        fs.writeFileSync(
            path.join(distDir, 'preload-manifest.json'),
            JSON.stringify({
                css: 'static/index-AAAA1111.css',
                font: 'static/assets/Inter-BBBB2222.woff2',
                js: ['static/index-CCCC3333.js'],
                authenticatedJs: ['static/AuthenticatedShell-DDDD4444.js'],
            })
        )
        fs.writeFileSync(path.join(distDir, 'index-CCCC3333.js'), 'console.log("entry")')

        upstreamRequests = []
        upstream = http.createServer((req, res) => {
            const chunks: Buffer[] = []
            req.on('data', (chunk) => chunks.push(chunk))
            req.on('end', () => {
                upstreamRequests.push({
                    method: req.method || '',
                    url: req.url || '',
                    headers: req.headers,
                    body: Buffer.concat(chunks).toString(),
                })
                const status = Number(req.headers['x-test-response-status']) || 200
                res.writeHead(status, { 'content-type': 'application/json', 'set-cookie': 'session=abc' })
                res.end(JSON.stringify({ ok: status === 200, path: req.url }))
            })
        })
        upstreamOrigin = await new Promise<string>((resolve) => {
            upstream.listen(0, '127.0.0.1', () => {
                const address = upstream.address() as { port: number }
                resolve(`http://127.0.0.1:${address.port}`)
            })
        })

        auth = { apiHost: upstreamOrigin, accessToken: 'phx_test_key' }
        signOutRequests = 0
        authRejections = 0
        backend = await startLocalBackend(
            {
                distDir,
                cacheDir,
                getAuth: () => auth,
                onOAuthCallback: async (query) => ({
                    ok: query.get('code') === 'good',
                    message: `handled:${query.get('state')}`,
                }),
                onSignOutRequested: () => {
                    signOutRequests += 1
                },
                onAuthRejected: () => {
                    authRejections += 1
                },
                upstreamHeaders: { 'user-agent': 'PostHog-Desktop/test' },
            },
            0
        )
    })

    after(async () => {
        await backend.close()
        upstream.closeAllConnections()
        await new Promise<void>((resolve) => upstream.close(() => resolve()))
        fs.rmSync(tmpDir, { recursive: true, force: true })
    })

    beforeEach(() => {
        auth = { apiHost: upstreamOrigin, accessToken: 'phx_test_key' }
        upstreamRequests.length = 0
    })

    test('serves the generated index.html for SPA routes', async () => {
        for (const route of ['/', '/insights', '/project/2/dashboard/1']) {
            const response = await fetch(backend.origin + route)
            assert.equal(response.status, 200)
            const body = await response.text()
            assert.match(body, /static\/index-CCCC3333\.js/)
            assert.doesNotMatch(body, /POSTHOG_APP_CONTEXT/)
        }
    })

    test('serves static assets with immutable caching for hashed files', async () => {
        const response = await fetch(`${backend.origin}/static/index-CCCC3333.js`)
        assert.equal(response.status, 200)
        assert.equal(response.headers.get('content-type'), 'application/javascript')
        assert.match(response.headers.get('cache-control') || '', /immutable/)
        assert.equal(await response.text(), 'console.log("entry")')
    })

    test('blocks path traversal out of the dist directory', async () => {
        const response = await fetch(`${backend.origin}/static/..%2f..%2fetc%2fpasswd`)
        assert.equal(response.status, 404)
    })

    test('proxies API requests upstream with a bearer token and without cookies', async () => {
        const response = await fetch(`${backend.origin}/api/users/@me/extra?q=1`, {
            headers: { cookie: 'local=1', 'x-custom': 'kept' },
        })
        assert.equal(response.status, 200)
        assert.equal(response.headers.get('set-cookie'), null)
        const seen = upstreamRequests[0]
        assert.equal(seen.url, '/api/users/@me/extra?q=1')
        assert.equal(seen.headers['authorization'], 'Bearer phx_test_key')
        assert.equal(seen.headers['cookie'], undefined)
        assert.equal(seen.headers['x-custom'], 'kept')
        assert.equal(seen.headers['user-agent'], 'PostHog-Desktop/test')
    })

    test('forwards request bodies for mutating methods', async () => {
        const response = await fetch(`${backend.origin}/api/projects/1/insights/`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ name: 'test' }),
        })
        assert.equal(response.status, 200)
        assert.equal(upstreamRequests[0].method, 'POST')
        assert.equal(upstreamRequests[0].body, JSON.stringify({ name: 'test' }))
    })

    test('returns 401 for proxy paths when signed out', async () => {
        auth = null
        const response = await fetch(`${backend.origin}/api/users/@me/`)
        assert.equal(response.status, 401)
        const body = (await response.json()) as { code: string }
        assert.equal(body.code, 'desktop_not_signed_in')
        assert.equal(upstreamRequests.length, 0)
    })

    test('serves cached bootstrap responses when the upstream is unreachable', async () => {
        const warm = await fetch(`${backend.origin}/api/users/@me/`)
        assert.equal(warm.status, 200)

        auth = { apiHost: 'http://127.0.0.1:1', accessToken: 'phx_test_key' }
        const offline = await fetch(`${backend.origin}/api/users/@me/`)
        assert.equal(offline.status, 200)
        assert.equal(offline.headers.get('x-posthog-desktop-cache'), 'stale')
        const body = (await offline.json()) as { ok: boolean }
        assert.equal(body.ok, true)

        const uncached = await fetch(`${backend.origin}/api/projects/1/`)
        assert.equal(uncached.status, 503)
    })

    test('reports rejected credentials only when the upstream 401s the identity check', async () => {
        const rejected = await fetch(`${backend.origin}/api/users/@me/`, {
            headers: { 'x-test-response-status': '401' },
        })
        assert.equal(rejected.status, 401)
        assert.equal(authRejections, 1)

        const otherPath = await fetch(`${backend.origin}/api/projects/1/`, {
            headers: { 'x-test-response-status': '401' },
        })
        assert.equal(otherPath.status, 401)
        assert.equal(authRejections, 1)
    })

    test('/logout notifies the host and never reaches the upstream', async () => {
        const response = await fetch(`${backend.origin}/logout`)
        assert.equal(response.status, 200)
        assert.equal(signOutRequests, 1)
        assert.equal(upstreamRequests.length, 0)
    })

    test('/callback is routed to the OAuth handler instead of the SPA', async () => {
        const response = await fetch(`${backend.origin}/callback?code=good&state=xyz`)
        assert.equal(response.status, 200)
        const body = await response.text()
        assert.match(body, /handled:xyz/)
        assert.equal(upstreamRequests.length, 0)
    })

    test('isProxyPath separates backend paths from SPA routes', () => {
        for (const proxied of ['/api/users/@me/', '/_preflight/', '/uploaded_media/x.png', '/decide', '/flags?v=2']) {
            assert.equal(isProxyPath(proxied), true, proxied)
        }
        for (const spa of ['/', '/insights', '/settings/user-api-keys', '/apiary', '/events']) {
            assert.equal(isProxyPath(spa), false, spa)
        }
    })
})
