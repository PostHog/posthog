import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleEmaTrustedIssuer } from '@/handlers/ema'
import { handleToken } from '@/handlers/token'
import { hashKey } from '@/lib/kv'

import { createMockKV, mockKVGet } from './helpers'

const mockKV = createMockKV()

beforeEach(() => {
    vi.clearAllMocks()
})

describe('EMA setup through the proxy', () => {
    it('points the setup endpoint of a regional token response at the proxy', async () => {
        const clientHash = await hashKey('ema_client')
        mockKVGet(mockKV, (key: string) => Promise.resolve(key === `region:${clientHash}` ? 'eu' : null))
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({
                        access_token: 'pha_ema_token',
                        token_type: 'Bearer',
                        scope: 'ema_issuer:manage',
                        ema_setup_endpoint: 'https://eu.posthog.com/oauth/ema/trusted-issuer/',
                    }),
                    { status: 200, headers: { 'Content-Type': 'application/json' } }
                )
            )
        )

        const response = await handleToken(
            new Request('https://oauth.posthog.com/oauth/token/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'grant_type=authorization_code&code=test_code&client_id=ema_client',
            }),
            mockKV,
            {}
        )

        expect(response.status).toBe(200)
        expect(await response.json()).toMatchObject({
            access_token: 'pha_ema_token',
            ema_setup_endpoint: 'https://oauth.posthog.com/oauth/ema/trusted-issuer/?region=eu',
        })
    })

    it('forwards the setup call to the region in the query, with its token and body', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{"aud_tenant":"org"}', { status: 200 })))

        const response = await handleEmaTrustedIssuer(
            new Request('https://oauth.posthog.com/oauth/ema/trusted-issuer/?region=eu', {
                method: 'PUT',
                headers: { Authorization: 'Bearer pha_ema_token', 'Content-Type': 'application/json' },
                body: JSON.stringify({ ema_issuer: 'https://identity.example.com/issuers/1' }),
            })
        )

        expect(response.status).toBe(200)
        const [url, init] = vi.mocked(fetch).mock.calls[0]!
        expect(String(url)).toBe('https://eu.posthog.com/oauth/ema/trusted-issuer/')
        expect(init?.method).toBe('PUT')
        expect(new Headers(init?.headers).get('authorization')).toBe('Bearer pha_ema_token')
        expect(await new Response(init?.body).text()).toBe('{"ema_issuer":"https://identity.example.com/issuers/1"}')
    })

    it('refuses a setup call without a known region', async () => {
        vi.stubGlobal('fetch', vi.fn())

        const response = await handleEmaTrustedIssuer(
            new Request('https://oauth.posthog.com/oauth/ema/trusted-issuer/', { method: 'PUT', body: '{}' })
        )

        expect(response.status).toBe(400)
        expect(fetch).not.toHaveBeenCalled()
    })
})
