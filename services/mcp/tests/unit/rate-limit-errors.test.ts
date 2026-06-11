import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { handleToolError, parseRetryAfterSeconds, PostHogApiError, PostHogRateLimitError } from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))
vi.mock('@/lib/posthog/analytics', () => ({
    AnalyticsEvent: { MCP_INIT: 'mcp init' },
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
        const stub429 = (headers?: Record<string, string>): ReturnType<typeof vi.fn> => {
            const mockFetch = vi
                .fn()
                .mockResolvedValue(
                    new Response(JSON.stringify({ detail: 'Request was throttled.' }), { status: 429, headers })
                )
            vi.stubGlobal('fetch', mockFetch)
            return mockFetch
        }

        const buildClient = (): ApiClient => new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })

        it('fails immediately with PostHogRateLimitError carrying Retry-After', async () => {
            const mockFetch = stub429({ 'Retry-After': '12' })

            const result = await buildClient().users().me()

            expect(result.success).toBe(false)
            if (result.success) {
                throw new Error('expected failure')
            }
            expect(result.error).toBeInstanceOf(PostHogRateLimitError)
            const rateLimitError = result.error as PostHogRateLimitError
            expect(rateLimitError.retryAfterSeconds).toBe(12)
            expect(rateLimitError.message).toContain('Retry after 12 seconds')
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('treats a missing Retry-After header as unknown', async () => {
            const mockFetch = stub429()

            const result = await buildClient().users().me()

            expect(result.success).toBe(false)
            if (result.success) {
                throw new Error('expected failure')
            }
            expect((result.error as PostHogRateLimitError).retryAfterSeconds).toBeNull()
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })

        it('propagates the error through ApiClient.request()', async () => {
            stub429({ 'Retry-After': '30' })

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
