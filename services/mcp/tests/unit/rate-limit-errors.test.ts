import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient, type Result } from '@/api/client'
import {
    findRecoverableApiError,
    handleToolError,
    parseRetryAfterSeconds,
    PostHogApiError,
    PostHogRateLimitError,
    wrapError,
} from '@/lib/errors'
import { getLLMCostsHandler } from '@/tools/aiObservability/getLLMCosts'
import { parserRecipeCreateHandler } from '@/tools/aiObservability/parserRecipeCreate'
import { queryHandler } from '@/tools/insights/query'
import { getProjectsHandler } from '@/tools/projects/getProjects'
import { updateEventDefinitionHandler } from '@/tools/projects/updateEventDefinition'
import { updatePathCleaningHandler } from '@/tools/projects/updatePathCleaning'
import { updatePropertyDefinitionHandler } from '@/tools/projects/updatePropertyDefinition'
import type { Context } from '@/tools/types'

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
            { header: ' 45 ', expected: 45 },
            { header: '1.5', expected: null },
            { header: '45seconds', expected: null },
            { header: '9'.repeat(400), expected: null },
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

describe('outbound 503 retry hints', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        vi.useFakeTimers()
        vi.spyOn(console, 'error').mockImplementation(() => {})
    })

    afterEach(() => {
        vi.useRealTimers()
        vi.restoreAllMocks()
        vi.unstubAllGlobals()
    })

    async function unwrapResult(resultPromise: Promise<Result<unknown>>): Promise<unknown> {
        const result = await resultPromise
        if (!result.success) {
            throw result.error
        }
        return result.data
    }

    it.each<{
        name: string
        request: (context: Context) => Promise<unknown>
        precedingResponses?: unknown[]
    }>([
        {
            name: 'property definitions list',
            request: ({ api }) => unwrapResult(api.projects().propertyDefinitions({ projectId: '123' })),
        },
        {
            name: 'event definitions list',
            request: ({ api }) => unwrapResult(api.projects().eventDefinitions({ projectId: '123' })),
        },
        {
            name: 'insight delete',
            request: ({ api }) => unwrapResult(api.insights({ projectId: '123' }).delete({ insightId: 456 })),
        },
        ...[false, true].flatMap((duringUpdate) => [
            {
                name: `event definition ${duringUpdate ? 'update' : 'lookup'}`,
                request: (context: Context) =>
                    updateEventDefinitionHandler(context, { eventName: 'test_event', data: { description: 'Test' } }),
                precedingResponses: duringUpdate ? [{ id: 'event-id', name: 'test_event' }] : [],
            },
            {
                name: `property definition ${duringUpdate ? 'update' : 'lookup'}`,
                request: (context: Context) =>
                    updatePropertyDefinitionHandler(context, {
                        propertyName: 'test_property',
                        type: 'event',
                        data: { description: 'Test' },
                    }),
                precedingResponses: duringUpdate ? [{ results: [{ id: 'property-id', name: 'test_property' }] }] : [],
            },
            {
                name: `insight ${duringUpdate ? 'query' : 'lookup'}`,
                request: (context: Context) => queryHandler(context, { insightId: '456', output_format: 'json' }),
                precedingResponses: duringUpdate ? [{ id: 456, query: { kind: 'HogQLQuery', query: 'SELECT 1' } }] : [],
            },
            {
                name: `path cleaning ${duringUpdate ? 'update' : 'lookup'}`,
                request: (context: Context) =>
                    updatePathCleaningHandler(context, {
                        operations: [{ action: 'append', alias: '/items/id', regex: '^/items/[0-9]+$' }],
                        confirm: true,
                    }),
                precedingResponses: duringUpdate ? [{ path_cleaning_filters: [] }] : [],
            },
        ]),
        { name: 'group types', request: ({ api }) => api.getGroupTypes('123') },
        { name: 'gateway tools', request: ({ api }) => api.getGatewayTools('123') },
        { name: 'project discovery', request: (context) => getProjectsHandler(context, {}) },
        { name: 'LLM costs', request: (context) => getLLMCostsHandler(context, {}) },
        {
            name: 'parser recipe trace',
            request: (context) =>
                parserRecipeCreateHandler(context, {
                    name: 'Test recipe',
                    yaml_source: 'test: true',
                    trace_id: 'test-trace',
                    event_uuid: 'test-event',
                }),
        },
    ])('preserves the cooldown through the $name path', async ({ request, precedingResponses = [] }) => {
        const mockFetch = vi.fn()
        for (const response of precedingResponses) {
            mockFetch.mockResolvedValueOnce(new Response(JSON.stringify(response), { status: 200 }))
        }
        mockFetch.mockResolvedValueOnce(
            new Response('Temporarily unavailable', { status: 503, headers: { 'Retry-After': '45' } })
        )
        vi.stubGlobal('fetch', mockFetch)
        const context = {
            api: new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://example.com' }),
            stateManager: { getProjectId: async () => '123', getOrgID: async () => 'test-org' },
        } as unknown as Context

        const error = await request(context).catch((error: unknown) => error)

        expect(findRecoverableApiError(error)).toMatchObject({ status: 503, retryAfterSeconds: 45 })
        const result = handleToolError(error, 'test-tool')
        expect(result.isError).toBe(true)
        expect(result.content[0]).toMatchObject({
            type: 'text',
            text: expect.stringContaining('Wait at least 45 seconds'),
        })
        expect(mockFetch).toHaveBeenCalledTimes(precedingResponses.length + 1)
        expect(vi.getTimerCount()).toBe(0)
    })

    it.each([
        { transport: 'json', wrapped: false },
        { transport: 'json', wrapped: true },
        { transport: 'text', wrapped: false },
        { transport: 'text', wrapped: true },
        { transport: 'sse', wrapped: false },
        { transport: 'sse', wrapped: true },
    ])(
        'passes the server cooldown to the agent without retrying ($transport, wrapped=$wrapped)',
        async ({ transport, wrapped }) => {
            const body = JSON.stringify({
                type: 'server_error',
                code: 'service_unavailable',
                detail: 'Please try later.',
            })
            const mockFetch = vi.fn().mockResolvedValue(
                new Response(body, {
                    status: 503,
                    statusText: 'Service Unavailable',
                    headers: { 'Retry-After': '45' },
                })
            )
            vi.stubGlobal('fetch', mockFetch)
            const client = new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://example.com' })
            const options = { method: 'POST' as const, path: '/api/projects/123/logs/query/', body: {} }
            const request =
                transport === 'sse'
                    ? client.requestSSE({ ...options, onEvent: vi.fn() })
                    : client.request({ ...options, responseType: transport === 'text' ? 'text' : 'json' })
            const error = await request.catch((error: unknown) => error)

            expect(error).toBeInstanceOf(PostHogApiError)
            expect(error).toMatchObject({ status: 503, body, retryAfterSeconds: 45 })
            const result = handleToolError(wrapped ? wrapError('Failed to query logs', error) : error, 'query-logs')
            expect(result.isError).toBe(true)
            expect(result.content[0]).toMatchObject({
                type: 'text',
                text: expect.stringContaining('Wait at least 45 seconds'),
            })
            expect((result.content[0] as { text: string }).text).not.toContain('Narrow the query and retry')
            expect(captureException).toHaveBeenCalledTimes(1)
            expect(mockFetch).toHaveBeenCalledTimes(1)
            expect(vi.getTimerCount()).toBe(0)
        }
    )

    it.each([
        { status: 503, header: '0', expected: 0 },
        { status: 503, header: '45', expected: 45 },
        { status: 503, header: null, expected: null },
        { status: 503, header: 'unknown', expected: null },
        { status: 503, header: '-1', expected: null },
        { status: 503, header: '45seconds', expected: null },
        { status: 503, header: 'Wed, 21 Oct 2026 07:28:00 GMT', expected: null },
        { status: 500, header: '45', expected: null },
    ])('only returns valid 503 cooldowns (status=$status, header=$header)', async ({ status, header, expected }) => {
        const mockFetch = vi.fn().mockResolvedValue(
            new Response('Upstream failure', {
                status,
                headers: header === null ? {} : { 'Retry-After': header },
            })
        )
        vi.stubGlobal('fetch', mockFetch)
        const client = new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://example.com' })
        const error = await client
            .request({ method: 'GET', path: '/api/projects/123/logs/query/' })
            .catch((error: unknown) => error)

        expect(error).toMatchObject({ status, retryAfterSeconds: expected })
        const result = handleToolError(error, 'query-logs')
        const text = (result.content[0] as { text: string }).text
        if (expected === null) {
            expect(text).not.toContain('Wait at least')
            expect(text).toContain('Narrow the query and retry')
        } else {
            expect(text).toContain(`Wait at least ${expected} seconds`)
        }
        expect(mockFetch).toHaveBeenCalledTimes(1)
    })
})
