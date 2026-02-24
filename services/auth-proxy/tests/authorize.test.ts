import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleAuthorize } from '@/handlers/authorize'

import { createMockKV, mockKVGet } from './helpers'

const mockKV = createMockKV()

beforeEach(() => {
    vi.clearAllMocks()
})

describe('handleAuthorize', () => {
    it('shows region picker when no _region param', async () => {
        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=abc&redirect_uri=http://localhost:3000/callback&response_type=code'
        )
        const response = await handleAuthorize(request, mockKV)

        expect(response.status).toBe(200)
        expect(response.headers.get('content-type')).toContain('text/html')

        const html = await response.text()
        expect(html).toContain('Log in to PostHog')
        expect(html).toContain('US Cloud')
        expect(html).toContain('EU Cloud')
    })

    it('redirects to US authorize with translated client_id when _region=us', async () => {
        const mapping = { us_client_id: 'us_real_id', eu_client_id: 'eu_real_id', created_at: Date.now() }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=us_real_id&redirect_uri=http://localhost:3000/callback&response_type=code&_region=us'
        )
        const response = await handleAuthorize(request, mockKV)

        expect(response.status).toBe(302)
        const location = response.headers.get('location')!
        expect(location).toContain('us.posthog.com/oauth/authorize/')
        expect(location).toContain('client_id=us_real_id')
        expect(location).not.toContain('_region')
    })

    it('redirects to EU authorize with translated client_id when _region=eu', async () => {
        const mapping = { us_client_id: 'us_real_id', eu_client_id: 'eu_real_id', created_at: Date.now() }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=us_real_id&redirect_uri=http://localhost:3000/callback&response_type=code&_region=eu'
        )
        const response = await handleAuthorize(request, mockKV)

        expect(response.status).toBe(302)
        const location = response.headers.get('location')!
        expect(location).toContain('eu.posthog.com/oauth/authorize/')
        expect(location).toContain('client_id=eu_real_id')
        expect(location).not.toContain('_region')
    })

    it('stores region selection keyed by both state and client_id', async () => {
        const mapping = { us_client_id: 'us_id', eu_client_id: 'eu_id', created_at: Date.now() }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=us_id&response_type=code&state=abc123&_region=eu'
        )
        await handleAuthorize(request, mockKV)

        const putCalls = vi.mocked(mockKV.put).mock.calls
        const statePut = putCalls.find(([key]) => (key as string) === 'region:abc123')
        const clientPut = putCalls.find(([key]) => (key as string) === 'region:us_id')
        expect(statePut).toBeTruthy()
        expect(statePut![1]).toBe('eu')
        expect(clientPut).toBeTruthy()
        expect(clientPut![1]).toBe('eu')
    })

    it('sets security headers on region picker page', async () => {
        const request = new Request('https://oauth.posthog.com/oauth/authorize/?client_id=abc&response_type=code')
        const response = await handleAuthorize(request, mockKV)

        expect(response.headers.get('x-frame-options')).toBe('DENY')
        expect(response.headers.get('x-content-type-options')).toBe('nosniff')
        expect(response.headers.get('referrer-policy')).toBe('no-referrer')
    })
})
