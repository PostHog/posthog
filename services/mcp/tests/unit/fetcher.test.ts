import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buildApiFetcher, type Fetcher } from '@/api/fetcher'
import { PostHogApiError, PostHogRateLimitError } from '@/lib/errors'

type FetchInput = Parameters<Fetcher['fetch']>[0]

describe('buildApiFetcher', () => {
    const mockConfig = {
        apiToken: 'test-token-123',
        baseUrl: 'https://api.example.com',
    }

    const baseFetchInput: FetchInput = {
        url: new URL('https://api.example.com/test'),
        method: 'get',
        path: '/test',
    }

    beforeEach(() => {
        vi.clearAllMocks()
        vi.useFakeTimers()
        global.fetch = vi.fn()
    })

    afterEach(() => {
        vi.restoreAllMocks()
    })

    describe('successful requests', () => {
        it('should make a successful GET request', async () => {
            const mockResponse = new Response(JSON.stringify({ data: 'test' }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' },
            })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const response = await fetcher.fetch(baseFetchInput)

            expect(response.ok).toBe(true)
            expect(global.fetch).toHaveBeenCalledTimes(1)
        })

        it('should include authorization header', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch(baseFetchInput)

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]!
            const headers = fetchCall[1]?.headers as Headers
            expect(headers.get('Authorization')).toBe('Bearer test-token-123')
        })

        it('should handle POST request with body', async () => {
            const mockResponse = new Response('{}', { status: 201 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                ...baseFetchInput,
                method: 'post',
                parameters: {
                    body: { name: 'test', value: 123 },
                },
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]!
            expect(fetchCall[1]?.method).toBe('POST')
            expect(fetchCall[1]?.body).toBe(JSON.stringify({ name: 'test', value: 123 }))
            const headers = fetchCall[1]?.headers as Headers
            expect(headers.get('Content-Type')).toBe('application/json')
        })

        it('should handle query parameters', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const url = new URL('https://api.example.com/test')
            const urlSearchParams = new URLSearchParams({ foo: 'bar', baz: 'qux' })

            await fetcher.fetch({
                ...baseFetchInput,
                url,
                urlSearchParams,
            })

            expect(url.search).toBe('?foo=bar&baz=qux')
        })

        it('should handle custom headers', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                ...baseFetchInput,
                parameters: {
                    header: {
                        'X-Custom-Header': 'custom-value',
                        'X-Another-Header': '123',
                    },
                },
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]!
            const headers = fetchCall[1]?.headers as Headers
            expect(headers.get('X-Custom-Header')).toBe('custom-value')
            expect(headers.get('X-Another-Header')).toBe('123')
        })
    })

    describe('429 handling', () => {
        it('should fail immediately with PostHogRateLimitError without retrying', async () => {
            const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
            vi.mocked(global.fetch).mockResolvedValue(
                new Response(JSON.stringify({ error: 'Rate limited' }), { status: 429 })
            )

            const fetcher = buildApiFetcher(mockConfig)
            const thrown = await fetcher.fetch(baseFetchInput).catch((err) => err)

            expect(thrown).toBeInstanceOf(PostHogRateLimitError)
            expect(thrown.status).toBe(429)
            expect(thrown.retryAfterSeconds).toBeNull()
            expect(global.fetch).toHaveBeenCalledTimes(1)

            consoleWarnSpy.mockRestore()
        })

        it.each([
            { header: '5', retryAfterSeconds: 5 },
            { header: '3600', retryAfterSeconds: 3600 },
        ])('should surface Retry-After ($header) in the error', async ({ header, retryAfterSeconds }) => {
            const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
            vi.mocked(global.fetch).mockResolvedValue(
                new Response('{}', { status: 429, headers: { 'Retry-After': header } })
            )

            const fetcher = buildApiFetcher(mockConfig)
            const thrown = await fetcher.fetch(baseFetchInput).catch((err) => err)

            expect(thrown).toBeInstanceOf(PostHogRateLimitError)
            expect(thrown.retryAfterSeconds).toBe(retryAfterSeconds)
            expect(thrown.message).toContain(`Retry after ${retryAfterSeconds} seconds`)
            expect(global.fetch).toHaveBeenCalledTimes(1)

            consoleWarnSpy.mockRestore()
        })

        it.each([{ header: '-5' }, { header: 'Wed, 21 Oct 2026 07:28:00 GMT' }])(
            'should treat invalid Retry-After ($header) as missing',
            async ({ header }) => {
                const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
                vi.mocked(global.fetch).mockResolvedValue(
                    new Response('{}', { status: 429, headers: { 'Retry-After': header } })
                )

                const fetcher = buildApiFetcher(mockConfig)
                const thrown = await fetcher.fetch(baseFetchInput).catch((err) => err)

                expect(thrown).toBeInstanceOf(PostHogRateLimitError)
                expect(thrown.retryAfterSeconds).toBeNull()

                consoleWarnSpy.mockRestore()
            }
        )
    })

    describe('error handling', () => {
        it('should throw a typed PostHogApiError on non-429 4xx responses', async () => {
            vi.mocked(global.fetch).mockResolvedValueOnce(
                new Response(JSON.stringify({ error: 'Not found' }), {
                    status: 404,
                    statusText: 'Not Found',
                })
            )

            const fetcher = buildApiFetcher(mockConfig)

            const thrown = await fetcher.fetch(baseFetchInput).catch((err) => err)
            expect(thrown).toBeInstanceOf(PostHogApiError)
            expect(thrown).toMatchObject({
                status: 404,
                statusText: 'Not Found',
            })
            expect(thrown.message).toContain('Failed request: [404]')

            // Should not retry on non-429 errors
            expect(global.fetch).toHaveBeenCalledTimes(1)
        })

        it('should throw a typed PostHogApiError on 5xx responses without retry', async () => {
            vi.mocked(global.fetch).mockResolvedValueOnce(
                new Response(JSON.stringify({ error: 'Internal error' }), {
                    status: 500,
                    statusText: 'Internal Server Error',
                })
            )

            const fetcher = buildApiFetcher(mockConfig)

            const thrown = await fetcher.fetch(baseFetchInput).catch((err) => err)
            expect(thrown).toBeInstanceOf(PostHogApiError)
            expect(thrown.status).toBe(500)
            expect(thrown.message).toContain('Failed request: [500]')

            expect(global.fetch).toHaveBeenCalledTimes(1)
        })
    })

    describe('HTTP methods', () => {
        it.each(['post', 'put', 'patch', 'delete'] as const)('should include body for %s requests', async (method) => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                ...baseFetchInput,
                method,
                parameters: {
                    body: { test: 'data' },
                },
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]!
            expect(fetchCall[1]?.body).toBe(JSON.stringify({ test: 'data' }))
            expect(fetchCall[1]?.method).toBe(method.toUpperCase())
        })

        it('should not include body for GET requests', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch(baseFetchInput)

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]!
            expect(fetchCall[1]?.body).toBeUndefined()
        })
    })
})
