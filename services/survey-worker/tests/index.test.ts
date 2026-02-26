import { describe, expect, it, vi, beforeEach } from 'vitest'

import worker, { getOrigin } from '../src/index'

describe('survey-worker', () => {
    describe('getOrigin', () => {
        it.each([
            { env: { POSTHOG_REGION: 'us' }, expected: 'https://us.posthog.com' },
            { env: { POSTHOG_REGION: 'US' }, expected: 'https://us.posthog.com' },
            { env: { POSTHOG_REGION: 'eu' }, expected: 'https://eu.posthog.com' },
            { env: { POSTHOG_REGION: 'EU' }, expected: 'https://eu.posthog.com' },
            { env: { POSTHOG_REGION: 'anything-else' }, expected: 'https://us.posthog.com' },
            { env: { POSTHOG_REGION: '' }, expected: 'https://us.posthog.com' },
        ])('POSTHOG_REGION=$env.POSTHOG_REGION → $expected', ({ env, expected }) => {
            expect(getOrigin(env)).toBe(expected)
        })

        it('POSTHOG_API_BASE_URL overrides region', () => {
            expect(getOrigin({ POSTHOG_REGION: 'eu', POSTHOG_API_BASE_URL: 'http://localhost:8010' })).toBe(
                'http://localhost:8010'
            )
        })
    })

    describe('fetch handler', () => {
        const env = { POSTHOG_REGION: 'us' }

        beforeEach(() => {
            vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('ok', { status: 200 })))
        })

        it('returns 404 for empty path', async () => {
            const request = new Request('https://surveys.mybrand.com/')
            const response = await worker.fetch(request, env)
            expect(response.status).toBe(404)
            expect(vi.mocked(fetch)).not.toHaveBeenCalled()
        })

        it('proxies to /external_surveys/<path>/ with domain param', async () => {
            const request = new Request('https://surveys.mybrand.com/abc-123')
            await worker.fetch(request, env)

            const [url, options] = vi.mocked(fetch).mock.calls[0]
            const proxied = new URL(url as string)
            expect(proxied.origin).toBe('https://us.posthog.com')
            expect(proxied.pathname).toBe('/external_surveys/abc-123/')
            expect(proxied.searchParams.get('domain')).toBe('surveys.mybrand.com')
            expect((options as RequestInit).headers).not.toBeUndefined()
            expect(new Headers(options!.headers as HeadersInit).get('Host')).toBe('us.posthog.com')
        })

        it('preserves query params from original request', async () => {
            const request = new Request('https://surveys.mybrand.com/abc-123?name=Jane&email=jane%40example.com')
            await worker.fetch(request, env)

            const proxied = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
            expect(proxied.searchParams.get('name')).toBe('Jane')
            expect(proxied.searchParams.get('email')).toBe('jane@example.com')
            expect(proxied.searchParams.get('domain')).toBe('surveys.mybrand.com')
        })

        it('routes to EU when region is eu', async () => {
            const request = new Request('https://surveys.mybrand.com/abc-123')
            await worker.fetch(request, { POSTHOG_REGION: 'eu' })

            const proxied = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
            expect(proxied.origin).toBe('https://eu.posthog.com')
        })

        it('strips leading and trailing slashes from path', async () => {
            const request = new Request('https://surveys.mybrand.com///abc-123///')
            await worker.fetch(request, env)

            const proxied = new URL(vi.mocked(fetch).mock.calls[0][0] as string)
            expect(proxied.pathname).toBe('/external_surveys/abc-123/')
        })
    })
})
