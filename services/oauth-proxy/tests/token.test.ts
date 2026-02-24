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
