import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleToken } from '@/handlers/token'

import { createMockKV, mockKVGet, mockKVGetValue } from './helpers'

const mockKV = createMockKV()

beforeEach(() => {
    vi.clearAllMocks()
})

describe('handleToken', () => {
    it('proxies to the correct region when region is stored in KV by client_id', async () => {
        mockKVGet(mockKV, (key: string, type?: unknown) => {
            if (key === 'region:proxy_client_123') {
                return Promise.resolve('us')
            }
            if (key === 'client:proxy_client_123' && type === 'json') {
                return Promise.resolve({
                    us_client_id: 'us_real_id',
                    eu_client_id: 'eu_real_id',
                    created_at: Date.now(),
                })
            }
            return Promise.resolve(null)
        })

        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({
                        access_token: 'pha_test_token',
                        token_type: 'bearer',
                    }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
        )

        const request = new Request('https://oauth.posthog.com/oauth/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'grant_type=authorization_code&code=test_code&client_id=proxy_client_123',
        })

        const response = await handleToken(request, mockKV)
        const data = (await response.json()) as Record<string, unknown>

        expect(response.status).toBe(200)
        expect(data.access_token).toBe('pha_test_token')

        const fetchCall = vi.mocked(fetch).mock.calls[0]!
        expect(String(fetchCall[0])).toMatch(/^https:\/\/us\.posthog\.com/)
    })

    it('rewrites redirect_uri when callback was intercepted by the proxy', async () => {
        mockKVGet(mockKV, (key: string, type?: unknown) => {
            if (key === 'region:proxy_client_456') {
                return Promise.resolve('eu')
            }
            if (key === 'callback:proxy_client_456') {
                return Promise.resolve('http://localhost:3000/callback')
            }
            if (key === 'client:proxy_client_456' && type === 'json') {
                return Promise.resolve({
                    us_client_id: 'us_real_id',
                    eu_client_id: 'eu_real_id',
                    created_at: Date.now(),
                })
            }
            return Promise.resolve(null)
        })

        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ access_token: 'pha_eu_token', token_type: 'bearer' }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            )
        )

        const request = new Request('https://oauth.posthog.com/oauth/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'grant_type=authorization_code&code=test_code&client_id=proxy_client_456&redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fcallback',
        })

        const response = await handleToken(request, mockKV)
        expect(response.status).toBe(200)

        const fetchCall = vi.mocked(fetch).mock.calls[0]!
        expect(String(fetchCall[0])).toMatch(/^https:\/\/eu\.posthog\.com/)

        // Verify redirect_uri was rewritten to proxy callback
        const sentBody = new URLSearchParams(fetchCall[1]!.body as string)
        expect(sentBody.get('redirect_uri')).toBe('https://oauth.posthog.com/oauth/callback/')
        expect(sentBody.get('client_id')).toBe('eu_real_id')
    })

    it('rewrites client_secret for confidential clients', async () => {
        mockKVGet(mockKV, (key: string, type?: unknown) => {
            if (key === 'region:proxy_client_789') {
                return Promise.resolve('eu')
            }
            if (key === 'callback:proxy_client_789') {
                return Promise.resolve('https://claude.ai/api/mcp/auth_callback')
            }
            if (key === 'client:proxy_client_789' && type === 'json') {
                return Promise.resolve({
                    us_client_id: 'proxy_client_789',
                    eu_client_id: 'eu_real_id',
                    us_client_secret: 'us_secret_abc',
                    eu_client_secret: 'eu_secret_xyz',
                    redirect_uris: ['https://claude.ai/api/mcp/auth_callback'],
                    created_at: Date.now(),
                })
            }
            return Promise.resolve(null)
        })

        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ access_token: 'pha_eu_token', token_type: 'bearer' }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' },
                })
            )
        )

        const request = new Request('https://oauth.posthog.com/oauth/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'grant_type=authorization_code&code=test_code&client_id=proxy_client_789&client_secret=us_secret_abc&redirect_uri=https%3A%2F%2Fclaude.ai%2Fapi%2Fmcp%2Fauth_callback',
        })

        const response = await handleToken(request, mockKV)
        expect(response.status).toBe(200)

        const fetchCall = vi.mocked(fetch).mock.calls[0]!
        const sentBody = new URLSearchParams(fetchCall[1]!.body as string)
        expect(sentBody.get('client_id')).toBe('eu_real_id')
        expect(sentBody.get('client_secret')).toBe('eu_secret_xyz')
        expect(sentBody.get('redirect_uri')).toBe('https://oauth.posthog.com/oauth/callback/')
    })

    it('returns error for authorization_code grant when region is unknown', async () => {
        mockKVGetValue(mockKV, null)

        const request = new Request('https://oauth.posthog.com/oauth/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'grant_type=authorization_code&code=test_code&client_id=unknown_client',
        })

        const response = await handleToken(request, mockKV)
        const data = (await response.json()) as Record<string, unknown>

        expect(response.status).toBe(400)
        expect(data.error).toBe('invalid_request')
    })

    it('falls back to try-both for refresh_token grants', async () => {
        mockKVGetValue(mockKV, null)

        vi.stubGlobal(
            'fetch',
            vi
                .fn()
                .mockResolvedValueOnce(
                    new Response(JSON.stringify({ error: 'invalid_grant' }), {
                        status: 400,
                        headers: { 'Content-Type': 'application/json' },
                    })
                )
                .mockResolvedValueOnce(
                    new Response(
                        JSON.stringify({
                            access_token: 'pha_eu_refreshed',
                            token_type: 'bearer',
                        }),
                        { status: 200, headers: { 'Content-Type': 'application/json' } }
                    )
                )
        )

        const request = new Request('https://oauth.posthog.com/oauth/token/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: 'grant_type=refresh_token&refresh_token=rt_test&client_id=unknown_client',
        })

        const response = await handleToken(request, mockKV)
        const data = (await response.json()) as Record<string, unknown>

        expect(data.access_token).toBe('pha_eu_refreshed')
        expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2)
    })
})
