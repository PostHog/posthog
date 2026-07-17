import * as assert from 'node:assert/strict'
import * as http from 'node:http'
import { after, before, beforeEach, describe, test } from 'node:test'

import { buildAuthorizeUrl, codeChallengeS256, OAuthBrowserFlow, refreshAccessToken } from './oauth.ts'

describe('oauth', () => {
    let tokenServer: http.Server
    let tokenServerOrigin: string
    let tokenResponses: { status: number; body: unknown }[]
    let tokenRequests: string[]

    before(async () => {
        tokenServer = http.createServer((req, res) => {
            const chunks: Buffer[] = []
            req.on('data', (chunk) => chunks.push(chunk))
            req.on('end', () => {
                tokenRequests.push(Buffer.concat(chunks).toString())
                const next = tokenResponses.shift() || { status: 500, body: {} }
                res.writeHead(next.status, { 'content-type': 'application/json' })
                res.end(JSON.stringify(next.body))
            })
        })
        tokenServerOrigin = await new Promise<string>((resolve) => {
            tokenServer.listen(0, '127.0.0.1', () => {
                const address = tokenServer.address() as { port: number }
                resolve(`http://127.0.0.1:${address.port}`)
            })
        })
    })

    after(() => {
        tokenServer.close()
        tokenServer.closeAllConnections()
    })

    beforeEach(() => {
        tokenResponses = []
        tokenRequests = []
    })

    test('computes the S256 code challenge per the RFC 7636 test vector', () => {
        assert.equal(
            codeChallengeS256('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
            'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
        )
    })

    test('authorize URL carries every protocol-required parameter', () => {
        const url = new URL(
            buildAuthorizeUrl({
                apiHost: 'https://us.posthog.com',
                clientId: 'client123',
                redirectUri: 'http://localhost:48752/callback',
                codeChallenge: 'challenge',
                state: 'state123',
            })
        )
        assert.equal(url.origin + url.pathname, 'https://us.posthog.com/oauth/authorize')
        assert.equal(url.searchParams.get('client_id'), 'client123')
        assert.equal(url.searchParams.get('redirect_uri'), 'http://localhost:48752/callback')
        assert.equal(url.searchParams.get('response_type'), 'code')
        assert.equal(url.searchParams.get('code_challenge_method'), 'S256')
        assert.equal(url.searchParams.get('scope'), '*')
        assert.equal(url.searchParams.get('state'), 'state123')
    })

    test('refresh distinguishes a rejected token (terminal) from an unreachable server (transient)', async () => {
        tokenResponses.push({ status: 400, body: { error: 'invalid_grant' } })
        const rejected = await refreshAccessToken({
            apiHost: tokenServerOrigin,
            clientId: 'client123',
            refreshToken: 'phr_dead',
        })
        assert.deepEqual(rejected, { ok: false, terminal: true })

        const unreachable = await refreshAccessToken({
            apiHost: 'http://127.0.0.1:1',
            clientId: 'client123',
            refreshToken: 'phr_fine',
        })
        assert.deepEqual(unreachable, { ok: false, terminal: false })
    })

    test('refresh maps a token response onto an absolute expiry', async () => {
        tokenResponses.push({
            status: 200,
            body: { access_token: 'pha_new', refresh_token: 'phr_new', expires_in: 3600 },
        })
        const before = Date.now()
        const result = await refreshAccessToken({
            apiHost: tokenServerOrigin,
            clientId: 'client123',
            refreshToken: 'phr_old',
        })
        assert.ok(result.ok)
        assert.equal(result.tokens.accessToken, 'pha_new')
        assert.equal(result.tokens.refreshToken, 'phr_new')
        assert.ok(result.tokens.expiresAt >= before + 3600 * 1000)
        assert.match(tokenRequests[0], /grant_type=refresh_token/)
    })

    test('callback with a mismatched state is rejected without killing the pending flow', async () => {
        const flow = new OAuthBrowserFlow()
        const { completion } = flow.begin({
            apiHost: tokenServerOrigin,
            clientId: 'client123',
            redirectUri: 'http://localhost:48752/callback',
        })
        const forged = await flow.handleCallback(new URLSearchParams({ code: 'stolen', state: 'wrong' }))
        assert.equal(forged.ok, false)
        assert.equal(tokenRequests.length, 0)

        // If the forged callback had settled the flow, this cancel reason could not win
        flow.cancel('test cleanup')
        const outcome = await completion
        assert.deepEqual(outcome, { ok: false, error: 'test cleanup' })
    })

    test('callback with the right state exchanges the code and resolves the flow', async () => {
        const flow = new OAuthBrowserFlow()
        const { url, completion } = flow.begin({
            apiHost: tokenServerOrigin,
            clientId: 'client123',
            redirectUri: 'http://localhost:48752/callback',
        })
        const state = new URL(url).searchParams.get('state')!
        tokenResponses.push({
            status: 200,
            body: { access_token: 'pha_ok', refresh_token: 'phr_ok', expires_in: 3600 },
        })
        const page = await flow.handleCallback(new URLSearchParams({ code: 'authcode', state }))
        assert.equal(page.ok, true)
        const result = await completion
        assert.ok(result.ok)
        assert.equal(result.tokens.accessToken, 'pha_ok')
        assert.match(tokenRequests[0], /grant_type=authorization_code/)
        assert.match(tokenRequests[0], /code=authcode/)
        assert.match(tokenRequests[0], /code_verifier=/)
    })
})
