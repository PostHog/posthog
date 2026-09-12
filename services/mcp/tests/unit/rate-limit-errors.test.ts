import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, type Result } from '@/api/client'
import { handleToolError, parseRetryAfterSeconds, PostHogApiError, PostHogRateLimitError } from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))
vi.mock('@/lib/posthog/analytics', () => ({
    AnalyticsEvent: { MCP_TOOL_CALL: '$mcp_tool_call' },
}))
vi.mock('@/lib/posthog/flags', () => ({
    isFeatureFlagEnabled: vi.fn().mockResolvedValue(false),
}))

describe('outbound 429 handling', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.spyOn(console, 'warn').mockImplementation(() => {})
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    describe('parseRetryAfterSeconds', () => {
        it.each([
            { header: '5', expected: 5 },
            { header: '0', expected: 0 },
            { header: '-5', expected: null },
            { header: 'Wed, 21 Oct 2026 07:28:00 GMT', expected: null },
            { header: null, expected: null },
        ])('parses $header as $expected', ({ header, expected }) => {
            expect(parseRetryAfterSeconds(header)).toBe(expected)
        })
    })

    describe('PostHogRateLimitError', () => {
        it('includes the retry hint when seconds are known', () => {
            const error = new PostHogRateLimitError({
                body: '{}',
                url: 'https://us.posthog.com/api/environments/2/query/',
                method: 'POST',
                retryAfterSeconds: 12,
            })

            expect(error).toBeInstanceOf(PostHogApiError)
            expect(error.status).toBe(429)
            expect(error.retryAfterSeconds).toBe(12)
            expect(error.message).toContain('Retry after 12 seconds')
        })

        it('omits the retry hint when seconds are unknown', () => {
            const error = new PostHogRateLimitError({
                body: '{}',
                url: 'https://us.posthog.com/api/users/@me/',
                method: 'GET',
                retryAfterSeconds: null,
            })

            expect(error.retryAfterSeconds).toBeNull()
            expect(error.message).not.toContain('Retry after')
        })
    })

    describe('ApiClient on 429', () => {
        const build429 = (headers?: Record<string, string>): Response =>
            new Response(JSON.stringify({ detail: 'Request was throttled.' }), { status: 429, headers })

        const stubFetch = (...responses: Response[]): ReturnType<typeof vi.fn> => {
            const mockFetch = vi.fn()
            for (const response of responses) {
                mockFetch.mockResolvedValueOnce(response)
            }
            // Persistent 429 once the scripted responses run out.
            mockFetch.mockImplementation(() => Promise.resolve(build429({ 'Retry-After': '1' })))
            vi.stubGlobal('fetch', mockFetch)
            return mockFetch
        }

        const buildClient = (): ApiClient => new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })

        const expectRateLimitFailure = (result: Result<unknown>): PostHogRateLimitError => {
            expect(result.success).toBe(false)
            if (result.success) {
                throw new Error('expected failure')
            }
            expect(result.error).toBeInstanceOf(PostHogRateLimitError)
            return result.error as PostHogRateLimitError
        }

        beforeEach(() => {
            vi.useFakeTimers()
        })

        afterEach(() => {
            vi.useRealTimers()
        })

        it('retries after the Retry-After delay and succeeds', async () => {
            const mockFetch = stubFetch(build429({ 'Retry-After': '5' }), new Response('{}', { status: 200 }))

            const resultPromise = buildClient().users().me()
            await vi.advanceTimersByTimeAsync(5000)
            const result = await resultPromise

            expect(result.success).toBe(true)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('falls back to jittered backoff when Retry-After is missing', async () => {
            const mockFetch = stubFetch(build429(), new Response('{}', { status: 200 }))

            const resultPromise = buildClient().users().me()
            // Jittered first-retry delay falls in [1000, 2000]ms.
            await vi.advanceTimersByTimeAsync(2000)
            const result = await resultPromise

            expect(result.success).toBe(true)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('returns PostHogRateLimitError after exhausting retries', async () => {
            const mockFetch = stubFetch()

            const resultPromise = buildClient().users().me()
            await vi.runAllTimersAsync()
            const rateLimitError = expectRateLimitFailure(await resultPromise)

            expect(rateLimitError.retryAfterSeconds).toBe(1)
            expect(rateLimitError.message).toContain('Retry after 1 seconds')
            expect(mockFetch).toHaveBeenCalledTimes(4)
        })

        it('fails fast without sleeping when Retry-After exceeds the wait budget', async () => {
            const mockFetch = stubFetch(build429({ 'Retry-After': '3600' }))

            const rateLimitError = expectRateLimitFailure(await buildClient().users().me())

            expect(rateLimitError.retryAfterSeconds).toBe(3600)
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('stops retrying once cumulative waits exhaust the budget', async () => {
            // 12s + 12s sleeps spend 24s of the 30s budget; the third 12s wait
            // exceeds the remaining 6s, so the client gives up after 3 attempts.
            const persistent429 = (): Promise<Response> => Promise.resolve(build429({ 'Retry-After': '12' }))
            const mockFetch = vi.fn().mockImplementation(persistent429)
            vi.stubGlobal('fetch', mockFetch)

            const resultPromise = buildClient().users().me()
            await vi.runAllTimersAsync()
            const rateLimitError = expectRateLimitFailure(await resultPromise)

            expect(rateLimitError.retryAfterSeconds).toBe(12)
            expect(mockFetch).toHaveBeenCalledTimes(3)
        })

        it('propagates the error through ApiClient.request()', async () => {
            stubFetch(build429({ 'Retry-After': '3600' }))

            await expect(buildClient().request({ method: 'GET', path: '/api/users/@me/' })).rejects.toBeInstanceOf(
                PostHogRateLimitError
            )
        })
    })

    describe('ApiClient on gateway timeout', () => {
        const buildTimeout = (status: number): Response => new Response('error code: 522', { status, statusText: '' })

        const buildClient = (): ApiClient => new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })

        beforeEach(() => {
            vi.useFakeTimers()
        })

        afterEach(() => {
            vi.useRealTimers()
        })

        it('retries a read (POST /query/) after a 522 and succeeds', async () => {
            const mockFetch = vi.fn()
            mockFetch.mockResolvedValueOnce(buildTimeout(522))
            mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ results: [] }), { status: 200 }))
            vi.stubGlobal('fetch', mockFetch)

            const resultPromise = buildClient().insights({ projectId: '2' }).query({ query: {} })
            await vi.runAllTimersAsync()
            const result = await resultPromise

            expect(result.success).toBe(true)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it.each([
            {
                label: 'a non-narrowable read (users/me) gets generic retry guidance',
                call: (c: ApiClient): Promise<Result<unknown>> => c.users().me(),
                expectNarrow: false,
            },
            {
                label: 'a narrowable query (POST /query/) gets narrow-and-retry advice',
                call: (c: ApiClient): Promise<Result<unknown>> => c.insights({ projectId: '2' }).query({ query: {} }),
                expectNarrow: true,
            },
        ])(
            'returns an actionable message instead of the proxy body after exhausting retries: $label',
            async ({ call, expectNarrow }) => {
                // Fresh Response per call, so each retry can read its own body (real fetch never
                // hands back an already-read Response).
                const mockFetch = vi.fn().mockImplementation(() => Promise.resolve(buildTimeout(522)))
                vi.stubGlobal('fetch', mockFetch)

                const resultPromise = call(buildClient())
                await vi.runAllTimersAsync()
                const result = await resultPromise

                expect(result.success).toBe(false)
                if (result.success) {
                    throw new Error('expected failure')
                }
                expect(result.error).toBeInstanceOf(PostHogApiError)
                expect((result.error as PostHogApiError).status).toBe(522)
                expect(result.error.message).not.toContain('error code: 522')
                if (expectNarrow) {
                    expect(result.error.message).toContain('Narrow the request')
                } else {
                    expect(result.error.message).not.toContain('Narrow the request')
                }
                expect(mockFetch).toHaveBeenCalledTimes(4)
            }
        )

        it('does not retry a mutating request and reports the write may have applied', async () => {
            const mockFetch = vi.fn().mockResolvedValue(buildTimeout(504))
            vi.stubGlobal('fetch', mockFetch)

            const result = await buildClient()
                .insights({ projectId: '2' })
                .create({ data: { name: 'x' } })

            expect(result.success).toBe(false)
            if (result.success) {
                throw new Error('expected failure')
            }
            expect((result.error as PostHogApiError).status).toBe(504)
            expect(result.error.message).toContain('may have already been applied')
            expect(result.error.message).not.toContain('error code: 504')
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('surfaces a structured API error (503) without retrying and keeps its detail', async () => {
            // A ClickHouse capacity 503 (and query-timeout 504) is a structured API error, not an
            // edge timeout: it must reach the agent with its detail and must not be retried.
            const detail = 'Queries are a little too busy right now. Please try again later.'
            const mockFetch = vi.fn().mockResolvedValue(
                new Response(JSON.stringify({ type: 'server_error', code: 'clickhouse_at_capacity', detail }), {
                    status: 503,
                    statusText: 'Service Unavailable',
                })
            )
            vi.stubGlobal('fetch', mockFetch)

            const result = await buildClient().insights({ projectId: '2' }).query({ query: {} })

            expect(result.success).toBe(false)
            if (result.success) {
                throw new Error('expected failure')
            }
            expect((result.error as PostHogApiError).status).toBe(503)
            expect(result.error.message).toContain(detail)
            expect(result.error.message).not.toContain('Narrow the request')
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })
    })

    describe('handleToolError on PostHogRateLimitError', () => {
        it('returns the retry hint to the agent without capturing an exception', () => {
            const error = new PostHogRateLimitError({
                body: '{}',
                url: 'https://us.posthog.com/api/environments/2/query/',
                method: 'POST',
                retryAfterSeconds: 12,
            })

            const result = handleToolError(error, 'query-run')

            expect(result.isError).toBe(true)
            const text = (result.content[0] as { text: string }).text
            expect(text).toContain('Retry after 12 seconds')
            expect(captureException).not.toHaveBeenCalled()
        })
    })
})
