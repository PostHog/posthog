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
