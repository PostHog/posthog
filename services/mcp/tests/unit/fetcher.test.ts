import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buildApiFetcher, type Fetcher } from '@/api/fetcher'
import { PostHogApiError } from '@/lib/errors'

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

    describe('exponential backoff on 429 rate limit', () => {
        it('should retry with exponential backoff on 429 response', async () => {
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch).mockResolvedValueOnce(mock429Response).mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch(baseFetchInput)

            // Advance time for first retry (jittered, at most 2000ms * 2^0)
            await vi.advanceTimersByTimeAsync(2000)
            await promise

            expect(global.fetch).toHaveBeenCalledTimes(2)
        })

        it('should use jittered exponential backoff delays capped at 2s, 4s, 8s', async () => {
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response) // Attempt 0: retry within 2s
                .mockResolvedValueOnce(mock429Response) // Attempt 1: retry within 4s
                .mockResolvedValueOnce(mock429Response) // Attempt 2: retry within 8s
                .mockResolvedValueOnce(mockSuccessResponse) // Attempt 3: success

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch(baseFetchInput)

            // Each retry's jittered delay falls in [backoff/2, backoff], so
            // advancing by the full backoff always releases it.
            await vi.advanceTimersByTimeAsync(2000)
            await vi.advanceTimersByTimeAsync(4000)
            await vi.advanceTimersByTimeAsync(8000)

            await promise

            expect(global.fetch).toHaveBeenCalledTimes(4)
        })

        it('should respect Retry-After header when present', async () => {
            const mock429Response = new Response('{}', {
                status: 429,
                headers: { 'Retry-After': '5' }, // 5 seconds
            })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch).mockResolvedValueOnce(mock429Response).mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch(baseFetchInput)

            // Should wait 5000ms (from Retry-After header) instead of 2000ms
            await vi.advanceTimersByTimeAsync(5000)
            await promise

            expect(global.fetch).toHaveBeenCalledTimes(2)
        })

        it('should throw error after max retries exceeded', async () => {
            const mock429Response = new Response(JSON.stringify({ error: 'Rate limited' }), {
                status: 429,
            })

            vi.mocked(global.fetch).mockResolvedValue(mock429Response)

            const fetcher = buildApiFetcher(mockConfig)

            // Start the fetch and immediately wrap in expect to catch rejection
            const fetchPromise = expect(fetcher.fetch(baseFetchInput)).rejects.toThrow(
                'Rate limit exceeded after 3 retries'
            )

            // Run all timers to completion
            await vi.runAllTimersAsync()

            // Wait for the assertion
            await fetchPromise

            expect(global.fetch).toHaveBeenCalledTimes(4) // Initial + 3 retries
        })

        it('should log warnings during retries', async () => {
            const consoleWarnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch).mockResolvedValueOnce(mock429Response).mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch(baseFetchInput)

            await vi.advanceTimersByTimeAsync(2000)
            await promise

            expect(consoleWarnSpy).toHaveBeenCalledWith(
                expect.stringMatching(/Rate limited \(429\)\. Retrying in \d+ms \(attempt 1\/3\)/)
            )

            consoleWarnSpy.mockRestore()
        })

        it('should fail fast without retrying when Retry-After exceeds the wait cap', async () => {
            const mock429Response = new Response(JSON.stringify({ error: 'Rate limited' }), {
                status: 429,
                headers: { 'Retry-After': '3600' },
            })
            vi.mocked(global.fetch).mockResolvedValue(mock429Response)

            const fetcher = buildApiFetcher(mockConfig)

            await expect(fetcher.fetch(baseFetchInput)).rejects.toThrow('above the 30s cap')

            expect(global.fetch).toHaveBeenCalledTimes(1)
        })
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
