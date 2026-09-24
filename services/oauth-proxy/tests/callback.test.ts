import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleCallback } from '@/handlers/callback'
import { hashKey } from '@/lib/kv'

import { createInMemoryKV, createMockKV, mockKVGet } from './helpers'

const mockKV = createMockKV()

beforeEach(() => {
    vi.clearAllMocks()
})

describe('handleCallback', () => {
    it("redirects to original redirect_uri with code and the client's original state", async () => {
        const nonceHash = await hashKey('proxy_nonce_123')
        mockKVGet(mockKV, (key: string) => {
            if (key === `pending_callback:${nonceHash}`) {
                return Promise.resolve({ redirect_uri: 'http://localhost:3000/callback', state: 'test_state_123' })
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=proxy_nonce_123'
        )
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('http://localhost:3000/callback')
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.get('state')).toBe('test_state_123')
    })

    it('keeps forwarding the code when the same callback arrives twice', async () => {
        const kv = createInMemoryKV()
        const nonceHash = await hashKey('replayed_nonce')
        await kv.put(
            `pending_callback:${nonceHash}`,
            JSON.stringify({ redirect_uri: 'http://localhost:3000/callback', state: 'orig_state' })
        )

        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=replayed_nonce')
        const first = await handleCallback(request, kv)
        expect(first.status).toBe(302)

        const second = await handleCallback(request, kv)
        expect(second.status).toBe(302)
        const location = new URL(second.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('http://localhost:3000/callback')
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.get('state')).toBe('orig_state')
    })

    it('carries no state param when the flow record has no client state', async () => {
        const nonceHash = await hashKey('nonce_no_state')
        mockKVGet(mockKV, (key: string) => {
            if (key === `pending_callback:${nonceHash}`) {
                return Promise.resolve({ redirect_uri: 'http://localhost:3000/callback', state: null })
            }
            return Promise.resolve(null)
        })

        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=nonce_no_state')
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.has('state')).toBe(false)
    })

    it.each([
        ['the state parameter is missing', 'https://oauth.posthog.com/oauth/callback/?code=auth_code_abc'],
        [
            'the nonce is expired or unknown',
            'https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=expired_state',
        ],
    ])('answers with a page the person can act on when %s', async (_case, url) => {
        mockKVGet(mockKV, () => Promise.resolve(null))

        const response = await handleCallback(new Request(url), mockKV)

        expect(response.status).toBe(400)
        expect(response.headers.get('content-type')).toContain('text/html')
        expect(await response.text()).toContain('sign in again')
    })

    it("forwards error params to the client's redirect_uri and restores its original state", async () => {
        const nonceHash = await hashKey('err_nonce')
        mockKVGet(mockKV, (key: string) => {
            if (key === `pending_callback:${nonceHash}`) {
                return Promise.resolve({ redirect_uri: 'http://localhost:3000/callback', state: 'client_err_state' })
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/callback/?error=access_denied&error_description=User+denied+access&state=err_nonce'
        )
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.searchParams.get('error')).toBe('access_denied')
        expect(location.searchParams.get('error_description')).toBe('User denied access')
        expect(location.searchParams.get('state')).toBe('client_err_state')
    })
})
