import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buildApiFetcher } from '@/api/fetcher'
import { globalRateLimiter } from '@/api/rate-limiter'

// Mock the global rate limiter
vi.mock('@/api/rate-limiter', () => ({
    globalRateLimiter: {
        throttle: vi.fn().mockResolvedValue(undefined),
    },
}))

describe('buildApiFetcher', () => {
    const mockConfig = {
        apiToken: 'test-token-123',
        baseUrl: 'https://api.example.com',
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
            const response = await fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            expect(response.ok).toBe(true)
            expect(global.fetch).toHaveBeenCalledTimes(1)
            expect(globalRateLimiter.throttle).toHaveBeenCalledTimes(1)
        })

        it('should include authorization header', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]
            const headers = fetchCall[1]?.headers as Headers
            expect(headers.get('Authorization')).toBe('Bearer test-token-123')
        })

        it('should handle POST request with body', async () => {
            const mockResponse = new Response('{}', { status: 201 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'post',
                parameters: {
                    body: { name: 'test', value: 123 },
                },
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]
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
                url,
                method: 'get',
                urlSearchParams,
            })

            expect(url.search).toBe('?foo=bar&baz=qux')
        })

        it('should handle custom headers', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
                parameters: {
                    header: {
                        'X-Custom-Header': 'custom-value',
                        'X-Another-Header': '123',
                    },
                },
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]
            const headers = fetchCall[1]?.headers as Headers
            expect(headers.get('X-Custom-Header')).toBe('custom-value')
            expect(headers.get('X-Another-Header')).toBe('123')
        })
    })

    describe('exponential backoff on 429 rate limit', () => {
        it('should retry with exponential backoff on 429 response', async () => {
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response)
                .mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            // Advance time for first retry (2000ms * 2^0 = 2000ms)
            await vi.advanceTimersByTimeAsync(2000)
            await promise

            expect(global.fetch).toHaveBeenCalledTimes(2)
            expect(globalRateLimiter.throttle).toHaveBeenCalledTimes(2)
        })

        it('should use exponential backoff delays: 2s, 4s, 8s', async () => {
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response) // Attempt 0: retry after 2s
                .mockResolvedValueOnce(mock429Response) // Attempt 1: retry after 4s
                .mockResolvedValueOnce(mock429Response) // Attempt 2: retry after 8s
                .mockResolvedValueOnce(mockSuccessResponse) // Attempt 3: success

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            // First retry: 2000ms * 2^0 = 2000ms
            await vi.advanceTimersByTimeAsync(2000)

            // Second retry: 2000ms * 2^1 = 4000ms
            await vi.advanceTimersByTimeAsync(4000)

            // Third retry: 2000ms * 2^2 = 8000ms
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

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response)
                .mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

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
            const fetchPromise = expect(
                fetcher.fetch({
                    url: new URL('https://api.example.com/test'),
                    method: 'get',
                })
            ).rejects.toThrow('Rate limit exceeded after 3 retries')

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

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response)
                .mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            await vi.advanceTimersByTimeAsync(2000)
            await promise

            expect(consoleWarnSpy).toHaveBeenCalledWith(
                expect.stringContaining('Rate limited (429). Retrying in 2000ms (attempt 1/3)')
            )

            consoleWarnSpy.mockRestore()
        })
    })

    describe('error handling', () => {
        it('should throw error on non-429 error responses', async () => {
            const mockErrorResponse = new Response(JSON.stringify({ error: 'Not found' }), {
                status: 404,
            })

            vi.mocked(global.fetch).mockResolvedValueOnce(mockErrorResponse)

            const fetcher = buildApiFetcher(mockConfig)

            await expect(
                fetcher.fetch({
                    url: new URL('https://api.example.com/test'),
                    method: 'get',
                })
            ).rejects.toThrow('Failed request: [404]')

            // Should not retry on non-429 errors
            expect(global.fetch).toHaveBeenCalledTimes(1)
        })

        it('should throw error on 500 server errors without retry', async () => {
            const mockErrorResponse = new Response(JSON.stringify({ error: 'Internal error' }), {
                status: 500,
            })

            vi.mocked(global.fetch).mockResolvedValueOnce(mockErrorResponse)

            const fetcher = buildApiFetcher(mockConfig)

            await expect(
                fetcher.fetch({
                    url: new URL('https://api.example.com/test'),
                    method: 'get',
                })
            ).rejects.toThrow('Failed request: [500]')

            expect(global.fetch).toHaveBeenCalledTimes(1)
        })
    })

    describe('rate limiter integration', () => {
        it('should call rate limiter before each request', async () => {
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response)
                .mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            await vi.advanceTimersByTimeAsync(2000)
            await promise

            // Should call throttle before initial request and before retry
            expect(globalRateLimiter.throttle).toHaveBeenCalledTimes(2)
        })

        it('should call rate limiter on all retry attempts', async () => {
            const mock429Response = new Response('{}', { status: 429 })
            const mockSuccessResponse = new Response('{}', { status: 200 })

            vi.mocked(global.fetch)
                .mockResolvedValueOnce(mock429Response)
                .mockResolvedValueOnce(mock429Response)
                .mockResolvedValueOnce(mockSuccessResponse)

            const fetcher = buildApiFetcher(mockConfig)
            const promise = fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            await vi.advanceTimersByTimeAsync(2000)
            await vi.advanceTimersByTimeAsync(4000)
            await promise

            // Initial + 2 retries = 3 calls
            expect(globalRateLimiter.throttle).toHaveBeenCalledTimes(3)
        })
    })

    describe('HTTP methods', () => {
        it.each(['post', 'put', 'patch', 'delete'])(
            'should include body for %s requests',
            async (method) => {
                const mockResponse = new Response('{}', { status: 200 })
                vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

                const fetcher = buildApiFetcher(mockConfig)
                await fetcher.fetch({
                    url: new URL('https://api.example.com/test'),
                    method,
                    parameters: {
                        body: { test: 'data' },
                    },
                })

                const fetchCall = vi.mocked(global.fetch).mock.calls[0]
                expect(fetchCall[1]?.body).toBe(JSON.stringify({ test: 'data' }))
                expect(fetchCall[1]?.method).toBe(method.toUpperCase())
            }
        )

        it('should not include body for GET requests', async () => {
            const mockResponse = new Response('{}', { status: 200 })
            vi.mocked(global.fetch).mockResolvedValueOnce(mockResponse)

            const fetcher = buildApiFetcher(mockConfig)
            await fetcher.fetch({
                url: new URL('https://api.example.com/test'),
                method: 'get',
            })

            const fetchCall = vi.mocked(global.fetch).mock.calls[0]
            expect(fetchCall[1]?.body).toBeUndefined()
        })
    })
})
