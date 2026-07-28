import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import worker from '@/index'

import { createMockKV } from './helpers'

const mockEnv = {
    AUTH_KV: {} as KVNamespace,
}

beforeEach(() => {
    vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
            ok: true,
            json: () =>
                Promise.resolve({
                    issuer: 'https://us.posthog.com',
                    authorization_endpoint: 'https://us.posthog.com/oauth/authorize/',
                    token_endpoint: 'https://us.posthog.com/oauth/token/',
                    revocation_endpoint: 'https://us.posthog.com/oauth/revoke/',
                    introspection_endpoint: 'https://us.posthog.com/oauth/introspect/',
                    userinfo_endpoint: 'https://us.posthog.com/oauth/userinfo/',
                    jwks_uri: 'https://us.posthog.com/.well-known/jwks.json',
                    registration_endpoint: 'https://us.posthog.com/oauth/register/',
                    scopes_supported: ['openid'],
                    response_types_supported: ['code'],
                    response_modes_supported: ['query'],
                    grant_types_supported: ['authorization_code', 'refresh_token'],
                    token_endpoint_auth_methods_supported: ['none'],
                    code_challenge_methods_supported: ['S256'],
                    service_documentation: 'https://posthog.com/docs/api',
                    client_id_metadata_document_supported: true,
                }),
        })
    )
})

afterEach(() => {
    vi.restoreAllMocks()
})

describe('router', () => {
    it.each([
        ['/', 200, 'text/plain'],
        ['/.well-known/oauth-authorization-server', 200, 'application/json'],
    ])('GET %s returns %d', async (path, expectedStatus, expectedContentType) => {
        const request = new Request(`https://oauth.posthog.com${path}`)
        const response = await worker.fetch(request, mockEnv)
        expect(response.status).toBe(expectedStatus)
        expect(response.headers.get('content-type')).toContain(expectedContentType)
    })

    it.each([
        'state',
        'client_id',
        'redirect_uri',
        'response_type',
        'scope',
        'code_challenge',
        'code_challenge_method',
    ])('rejects duplicate %s on /oauth/authorize before the handler runs', async (param) => {
        const kv = createMockKV()
        const request = new Request(
            `https://oauth.posthog.com/oauth/authorize/?client_id=abc&response_type=code&${param}=first&${param}=second&_region=us`
        )
        const response = await worker.fetch(request, { AUTH_KV: kv })

        expect(response.status).toBe(400)
        const data = (await response.json()) as Record<string, unknown>
        expect(data.error).toBe('invalid_request')
        expect(data.error_description).toBe(`Duplicate ${param} parameter is not allowed`)
        // Rejected at the router before the handler, so nothing is keyed in KV.
        expect(vi.mocked(kv.put)).not.toHaveBeenCalled()
    })

    it('returns 404 for unknown paths', async () => {
        const request = new Request('https://oauth.posthog.com/unknown')
        const response = await worker.fetch(request, mockEnv)
        expect(response.status).toBe(404)
    })

    it('returns the landing page at /', async () => {
        const request = new Request('https://oauth.posthog.com/')
        const response = await worker.fetch(request, mockEnv)
        const text = await response.text()
        expect(text).toContain('PostHog OAuth Proxy')
    })

    it('catches async handler rejections and returns 500 instead of crashing', async () => {
        // This is the core regression test for the `return await` fix in the router.
        // Without `await`, a rejected handler promise bypasses the try/catch and becomes
        // an unhandled rejection (Cloudflare Error 1101). With `await`, the catch block
        // intercepts it and returns a structured 500 response.
        vi.resetModules()

        // Mock handleAuthorize to return a rejected promise (simulates any async failure)
        vi.doMock('@/handlers/authorize', () => ({
            handleAuthorize: () => Promise.reject(new Error('KV transient failure')),
        }))

        const { default: freshWorker } = await import('@/index')
        const request = new Request('https://oauth.posthog.com/oauth/authorize/?client_id=abc')
        const response = await freshWorker.fetch(request, mockEnv)

        expect(response.status).toBe(500)
        const data = (await response.json()) as Record<string, unknown>
        expect(data.error).toBe('server_error')
        expect(data.error_description).toBe('An internal error occurred')
    })

    it('catches synchronous handler throws and returns 500', async () => {
        vi.resetModules()

        vi.doMock('@/handlers/authorize', () => ({
            handleAuthorize: () => {
                throw new Error('unexpected null')
            },
        }))

        const { default: freshWorker } = await import('@/index')
        const request = new Request('https://oauth.posthog.com/oauth/authorize/?client_id=abc')
        const response = await freshWorker.fetch(request, mockEnv)

        expect(response.status).toBe(500)
        const data = (await response.json()) as Record<string, unknown>
        expect(data.error).toBe('server_error')
    })
})
