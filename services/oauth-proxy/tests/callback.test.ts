import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleCallback } from '@/handlers/callback'
import { hashKey } from '@/lib/kv'

import { createMockKV, mockKVGet } from './helpers'

const mockKV = createMockKV()

beforeEach(() => {
    vi.clearAllMocks()
})

describe('handleCallback', () => {
    it('redirects to original redirect_uri with code and state', async () => {
        const stateHash = await hashKey('test_state_123')
        mockKVGet(mockKV, (key: string) => {
            if (key === `callback:${stateHash}`) {
                return Promise.resolve('http://localhost:3000/callback')
            }
            return Promise.resolve(null)
        })

        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=test_state_123')
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.origin + location.pathname).toBe('http://localhost:3000/callback')
        expect(location.searchParams.get('code')).toBe('auth_code_abc')
        expect(location.searchParams.get('state')).toBe('test_state_123')
    })

    it('returns 400 when state parameter is missing', async () => {
        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc')
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(400)
        expect(await response.text()).toBe('Missing state parameter')
    })

    it('returns 400 when state is expired or unknown', async () => {
        mockKVGet(mockKV, () => Promise.resolve(null))

        const request = new Request('https://oauth.posthog.com/oauth/callback/?code=auth_code_abc&state=expired_state')
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(400)
        expect(await response.text()).toBe('State expired or invalid')
    })

    it('forwards error params to client redirect_uri', async () => {
        const stateHash = await hashKey('err_state')
        mockKVGet(mockKV, (key: string) => {
            if (key === `callback:${stateHash}`) {
                return Promise.resolve('http://localhost:3000/callback')
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/callback/?error=access_denied&error_description=User+denied+access&state=err_state'
        )
        const response = await handleCallback(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.searchParams.get('error')).toBe('access_denied')
        expect(location.searchParams.get('error_description')).toBe('User denied access')
        expect(location.searchParams.get('state')).toBe('err_state')
    })
})
