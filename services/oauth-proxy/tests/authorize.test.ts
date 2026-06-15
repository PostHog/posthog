import { beforeEach, describe, expect, it, vi } from 'vitest'

import { handleAuthorize } from '@/handlers/authorize'
import { hashKey } from '@/lib/kv'

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

    it('redirects to US authorize with translated client_id and proxy callback when _region=us', async () => {
        const mapping = {
            us_client_id: 'us_real_id',
            eu_client_id: 'eu_real_id',
            redirect_uris: ['http://localhost:3000/callback'],
            created_at: Date.now(),
        }
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
        const location = new URL(response.headers.get('location')!)
        expect(location.origin).toBe('https://us.posthog.com')
        expect(location.pathname).toBe('/oauth/authorize/')
        expect(location.searchParams.get('client_id')).toBe('us_real_id')
        expect(location.searchParams.get('redirect_uri')).toBe('https://oauth.posthog.com/oauth/callback/')
        expect(location.searchParams.has('_region')).toBe(false)
    })

    it('redirects to EU authorize with translated client_id and proxy callback when _region=eu', async () => {
        const mapping = {
            us_client_id: 'us_real_id',
            eu_client_id: 'eu_real_id',
            redirect_uris: ['http://localhost:3000/callback'],
            created_at: Date.now(),
        }
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
        const location = new URL(response.headers.get('location')!)
        expect(location.origin).toBe('https://eu.posthog.com')
        expect(location.pathname).toBe('/oauth/authorize/')
        expect(location.searchParams.get('client_id')).toBe('eu_real_id')
        expect(location.searchParams.get('redirect_uri')).toBe('https://oauth.posthog.com/oauth/callback/')
        expect(location.searchParams.has('_region')).toBe(false)
    })

    it('rejects unregistered redirect_uri to prevent open redirects', async () => {
        const mapping = {
            us_client_id: 'us_id',
            eu_client_id: 'eu_id',
            redirect_uris: ['http://localhost:3000/callback'],
            created_at: Date.now(),
        }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=us_id&redirect_uri=https://attacker.com/steal&response_type=code&state=abc&_region=eu'
        )
        const response = await handleAuthorize(request, mockKV)

        expect(response.status).toBe(400)
        const data = (await response.json()) as Record<string, unknown>
        expect(data.error).toBe('invalid_request')
        expect(data.error_description).toBe('redirect_uri is not registered for this client')
    })

    it('stores region selection and callback redirect_uri keyed by state and client_id', async () => {
        const mapping = {
            us_client_id: 'us_id',
            eu_client_id: 'eu_id',
            redirect_uris: ['http://localhost:3000/callback'],
            created_at: Date.now(),
        }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=us_id&redirect_uri=http://localhost:3000/callback&response_type=code&state=abc123&_region=eu'
        )
        await handleAuthorize(request, mockKV)

        const putCalls = vi.mocked(mockKV.put).mock.calls

        const stateHash = await hashKey('abc123')
        const clientHash = await hashKey('us_id')

        // Region selection stored by both state and client_id
        const regionByState = putCalls.find(([key]) => (key as string) === `region:${stateHash}`)
        const regionByClient = putCalls.find(([key]) => (key as string) === `region:${clientHash}`)
        expect(regionByState).toBeTruthy()
        expect(regionByState![1]).toBe('eu')
        expect(regionByClient).toBeTruthy()
        expect(regionByClient![1]).toBe('eu')

        // Callback redirect_uri stored by both state and client_id
        const callbackByState = putCalls.find(([key]) => (key as string) === `callback:${stateHash}`)
        const callbackByClient = putCalls.find(([key]) => (key as string) === `callback:${clientHash}`)
        expect(callbackByState).toBeTruthy()
        expect(callbackByState![1]).toBe('http://localhost:3000/callback')
        expect(callbackByClient).toBeTruthy()
        expect(callbackByClient![1]).toBe('http://localhost:3000/callback')
    })

    it('writes bounded-length KV keys even for very large state values', async () => {
        const mapping = {
            us_client_id: 'us_id',
            eu_client_id: 'eu_id',
            redirect_uris: ['http://localhost:3000/callback'],
            created_at: Date.now(),
        }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        // A JWT-shaped state well above Cloudflare's 512-byte KV key limit.
        const longState = 'x'.repeat(2000)
        const request = new Request(
            `https://oauth.posthog.com/oauth/authorize/?client_id=us_id&redirect_uri=http://localhost:3000/callback&response_type=code&state=${longState}&_region=us`
        )
        const response = await handleAuthorize(request, mockKV)

        expect(response.status).toBe(302)
        const putCalls = vi.mocked(mockKV.put).mock.calls
        expect(putCalls.length).toBeGreaterThan(0)
        for (const [key] of putCalls) {
            expect((key as string).length).toBeLessThanOrEqual(512)
        }
    })

    it('passes redirect_uri through without interception for legacy clients (no stored redirect_uris)', async () => {
        const mapping = { us_client_id: 'us_id', eu_client_id: 'eu_id', created_at: Date.now() }
        mockKVGet(mockKV, (_key: string, type?: unknown) => {
            if (type === 'json') {
                return Promise.resolve(mapping)
            }
            return Promise.resolve(null)
        })

        const request = new Request(
            'https://oauth.posthog.com/oauth/authorize/?client_id=us_id&redirect_uri=http://localhost:3000/callback&response_type=code&_region=eu'
        )
        const response = await handleAuthorize(request, mockKV)

        expect(response.status).toBe(302)
        const location = new URL(response.headers.get('location')!)
        expect(location.searchParams.get('redirect_uri')).toBe('http://localhost:3000/callback')

        // No callback redirect_uri should be stored
        const putCalls = vi.mocked(mockKV.put).mock.calls
        const callbackPuts = putCalls.filter(([key]) => (key as string).startsWith('callback:'))
        expect(callbackPuts).toHaveLength(0)
    })

    it('sets security headers on region picker page', async () => {
        const request = new Request('https://oauth.posthog.com/oauth/authorize/?client_id=abc&response_type=code')
        const response = await handleAuthorize(request, mockKV)

        expect(response.headers.get('x-frame-options')).toBe('DENY')
        expect(response.headers.get('x-content-type-options')).toBe('nosniff')
        expect(response.headers.get('referrer-policy')).toBe('no-referrer')
    })
})
