import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, type Result } from '@/api/client'
import { handleToolError, PostHogApiError } from '@/lib/errors'

const captureException = vi.fn()
vi.mock('@/lib/posthog', () => ({
    getPostHogClient: () => ({ captureException }),
}))

describe('transient gateway 5xx handling', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.spyOn(console, 'warn').mockImplementation(() => {})
        vi.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    describe('ApiClient retry', () => {
        const build503 = (): Response =>
            new Response('<!DOCTYPE html><title>Error 503</title>', {
                status: 503,
                statusText: 'Service Unavailable',
            })

        const stubFetch = (...responses: Response[]): ReturnType<typeof vi.fn> => {
            const mockFetch = vi.fn()
            for (const response of responses) {
                mockFetch.mockResolvedValueOnce(response)
            }
            // Persistent 503 once the scripted responses run out.
            mockFetch.mockImplementation(() => Promise.resolve(build503()))
            vi.stubGlobal('fetch', mockFetch)
            return mockFetch
        }

        const buildClient = (): ApiClient => new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' })

        const expectApiFailure = (result: Result<unknown>): PostHogApiError => {
            expect(result.success).toBe(false)
            if (result.success) {
                throw new Error('expected failure')
            }
            expect(result.error).toBeInstanceOf(PostHogApiError)
            return result.error as PostHogApiError
        }

        beforeEach(() => {
            vi.useFakeTimers()
        })

        afterEach(() => {
            vi.useRealTimers()
        })

        it('retries a GET after a jittered backoff and succeeds', async () => {
            const mockFetch = stubFetch(build503(), new Response('{}', { status: 200 }))

            const resultPromise = buildClient().users().me()
            // Jittered first-retry delay falls in [1000, 2000]ms.
            await vi.advanceTimersByTimeAsync(2000)
            const result = await resultPromise

            expect(result.success).toBe(true)
            expect(mockFetch).toHaveBeenCalledTimes(2)
        })

        it('returns a PostHogApiError after exhausting retries on a persistent GET 503', async () => {
            const mockFetch = stubFetch()

            const resultPromise = buildClient().users().me()
            await vi.runAllTimersAsync()
            const error = expectApiFailure(await resultPromise)

            expect(error.status).toBe(503)
            expect(mockFetch).toHaveBeenCalledTimes(4)
        })

        it('does not retry a POST 503 — a mutation must not be replayed', async () => {
            const mockFetch = stubFetch()

            const error = expectApiFailure(await buildClient().insights({ projectId: '2' }).query({ query: {} }))

            expect(error.status).toBe(503)
            expect(mockFetch).toHaveBeenCalledTimes(1)
        })
    })

    describe('handleToolError fingerprint', () => {
        it.each([502, 503, 504])(
            'fingerprints a retry-exhausted %i once by status, not by tool name',
            (status: number) => {
                const error = new PostHogApiError({
                    status,
                    statusText: 'Service Unavailable',
                    body: '<!DOCTYPE html><title>Error 503</title>',
                    url: 'https://us.posthog.com/api/projects/2/dashboards/',
                    method: 'GET',
                })

                const result = handleToolError(error, 'dashboards-get')

                expect(result.isError).toBe(true)
                expect(captureException).toHaveBeenCalledTimes(1)
                const [, , properties] = captureException.mock.calls[0] as [unknown, unknown, Record<string, string>]
                expect(properties.$exception_fingerprint).toBe(`posthog-api-transient-5xx:${status}`)
                const text = (result.content[0] as { text: string }).text
                expect(text).toContain('transient gateway error')
            }
        )

        it('keeps the per-tool fingerprint for a non-transient 500', () => {
            const error = new PostHogApiError({
                status: 500,
                statusText: 'Internal Server Error',
                body: 'boom',
                url: 'https://us.posthog.com/api/projects/2/dashboards/',
                method: 'GET',
            })

            handleToolError(error, 'dashboards-get')

            const [, , properties] = captureException.mock.calls[0] as [unknown, unknown, Record<string, string>]
            expect(properties.$exception_fingerprint).toBe('dashboards-get')
        })
    })
})
