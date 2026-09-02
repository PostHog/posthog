import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { PostHogApiError, PostHogPermissionError, PostHogRateLimitError, PostHogValidationError } from '@/lib/errors'
import { invokeMcpTool } from '@/tools/posthogAiTools/invokeTool'
import type { Context } from '@/tools/types'

// A real client, so these run the path a tool actually takes — through the client's fetch seam,
// which is what points a request at the host the client was built for.
function makeContext(): Context {
    return {
        api: new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' }),
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue(2),
        },
    } as unknown as Context
}

describe('invokeMcpTool', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    afterEach(() => {
        vi.unstubAllGlobals()
    })

    const stubFetch = (response: Response): void => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    }

    it('returns the tool result on success', async () => {
        stubFetch(new Response(JSON.stringify({ success: true, content: 'rows' }), { status: 200 }))

        const result = await invokeMcpTool(makeContext(), 'execute_sql', { query: 'SELECT 1' })

        expect(result).toEqual({ success: true, content: 'rows' })
    })

    it('throws PostHogRateLimitError on a 429 so it is not bucketed as an internal error', async () => {
        // `Retry-After` is past the client's total retry budget, so this returns without waiting.
        stubFetch(
            new Response(JSON.stringify({ detail: 'Request was throttled.' }), {
                status: 429,
                headers: { 'Retry-After': '600' },
            })
        )

        const error = await invokeMcpTool(makeContext(), 'execute_sql', { query: 'SELECT 1' }).catch((e) => e)

        expect(error).toBeInstanceOf(PostHogRateLimitError)
        expect(error).toBeInstanceOf(PostHogApiError)
        expect((error as PostHogRateLimitError).status).toBe(429)
        expect((error as PostHogRateLimitError).retryAfterSeconds).toBe(600)
    })

    it('throws PostHogApiError carrying the status on a 5xx', async () => {
        stubFetch(new Response('upstream exploded', { status: 503, statusText: 'Service Unavailable' }))

        const error = await invokeMcpTool(makeContext(), 'execute_sql', { query: 'SELECT 1' }).catch((e) => e)

        expect(error).toBeInstanceOf(PostHogApiError)
        expect((error as PostHogApiError).status).toBe(503)
    })

    it('throws PostHogPermissionError on a 403 permission_denied', async () => {
        stubFetch(
            new Response(JSON.stringify({ code: 'permission_denied', detail: "required scope 'query:read'" }), {
                status: 403,
            })
        )

        const error = await invokeMcpTool(makeContext(), 'execute_sql', { query: 'SELECT 1' }).catch((e) => e)

        expect(error).toBeInstanceOf(PostHogPermissionError)
        expect((error as PostHogPermissionError).missingScope).toBe('query:read')
    })

    it('throws PostHogValidationError on a validation_error body', async () => {
        stubFetch(
            new Response(JSON.stringify({ type: 'validation_error', detail: 'bad query', attr: 'query' }), {
                status: 400,
            })
        )

        const error = await invokeMcpTool(makeContext(), 'execute_sql', { query: 'SELECT 1' }).catch((e) => e)

        expect(error).toBeInstanceOf(PostHogValidationError)
        expect((error as PostHogValidationError).attr).toBe('query')
    })
})
