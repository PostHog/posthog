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
            if (key === `flow:${nonceHash}`) {
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

    it('deletes the flow record after reading it, so the nonce is single-use', async () => {
        const kv = createInMemoryKV()
        const nonceHash = await hashKey('single_use_nonce')
        await kv.put(
            `flow:${nonceHash}`,
            JSON.stringify({ redirect_uri: 'http://localhost:3000/callback', state: 'orig_state' })
        )

        const request = new Request(
            'https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=single_use_nonce'
        )
        const first = await handleCallback(request, kv)
        expect(first.status).toBe(302)

        const second = await handleCallback(request, kv)
        expect(second.status).toBe(400)
        expect(await second.text()).toBe('State expired or invalid')
    })

    it('still redirects to the client when deleting the flow record fails', async () => {
        const nonceHash = await hashKey('delete_fails_nonce')
        mockKVGet(mockKV, (key: string) => {
            if (key === `flow:${nonceHash}`) {
                return Promise.resolve({ redirect_uri: 'http://localhost:3000/callback', state: 'orig_state' })
            }
            return Promise.resolve(null)
        })
        vi.mocked(mockKV.delete).mockRejectedValue(new Error('KV transient failure'))

        const request = new Request(
            'https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=delete_fails_nonce'
        )
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('http://localhost:3000/callback')
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.get('state')).toBe('orig_state')
    })

    it('carries no state param when the flow record has no client state', async () => {
        const nonceHash = await hashKey('nonce_no_state')
        mockKVGet(mockKV, (key: string) => {
            if (key === `flow:${nonceHash}`) {
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

    it('returns 400 when state parameter is missing', async () => {
        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc')
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(400)
        expect(await response.text()).toBe('Missing state parameter')
    })

    it('returns 400 when the nonce is expired or unknown', async () => {
        mockKVGet(mockKV, () => Promise.resolve(null))

        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=expired_state')
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(400)
        expect(await response.text()).toBe('State expired or invalid')
    })

    it("forwards error params to the client's redirect_uri and restores its original state", async () => {
        const nonceHash = await hashKey('err_nonce')
        mockKVGet(mockKV, (key: string) => {
            if (key === `flow:${nonceHash}`) {
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
