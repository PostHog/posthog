import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { GENERATED_TOOLS as CDP_TOOLS } from '@/tools/generated/cdp_functions'
import { GENERATED_TOOLS as LOGS_TOOLS } from '@/tools/generated/logs'
import type { Context } from '@/tools/types'

// Regression coverage for DRF comma-separated query filters (OpenAPI
// `style: form` + `explode: false`, e.g. hog_functions `type`). The shared
// ApiClient JSON-stringifies arrays for logs-style `json.loads()` params, so
// CSV params must be comma-joined in the generated handlers before they reach
// the client — otherwise DRF runs `type IN ('["..."]')` and silently matches
// nothing.

interface RequestArgs {
    method: string
    path: string
    query?: Record<string, unknown>
}

function createMockContext(): { context: Context; request: ReturnType<typeof vi.fn> } {
    const request = vi.fn().mockResolvedValue({ count: 0, results: [] })
    const context = {
        api: {
            request,
            getProjectBaseUrl: vi.fn().mockReturnValue('https://us.posthog.com/project/1'),
        },
        stateManager: {
            getProjectId: vi.fn().mockResolvedValue('1'),
            getOrgID: vi.fn(),
            getRegion: vi.fn().mockResolvedValue('us'),
        },
        env: { POSTHOG_BASE_URL: 'https://us.posthog.com' },
        sessionManager: {},
        cache: {},
        getDistinctId: async () => 'test',
    } as unknown as Context

    return { context, request }
}

describe('comma-separated (explode: false) query params in generated handlers', () => {
    it('cdp-functions-list joins type values with commas', async () => {
        const { context, request } = createMockContext()
        const tool = CDP_TOOLS['cdp-functions-list']!()

        await tool.handler(context, { type: ['internal_destination', 'transformation'] })

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.query?.type).toBe('internal_destination,transformation')
    })

    it('cdp-functions-list omits type when the array is empty', async () => {
        const { context, request } = createMockContext()
        const tool = CDP_TOOLS['cdp-functions-list']!()

        await tool.handler(context, { type: [] })

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.query?.type).toBeUndefined()
    })

    it('cdp-functions-list passes a single string type through unchanged', async () => {
        const { context, request } = createMockContext()
        const tool = CDP_TOOLS['cdp-functions-list']!()

        // Callers (and the integration suite) may pass a bare string instead of
        // an array — it must not hit Array.prototype.join.
        await tool.handler(context, { type: 'destination' } as never)

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.query?.type).toBe('destination')
    })

    it('logs-attribute-values-list keeps JSON-style array params as arrays', async () => {
        const { context, request } = createMockContext()
        const tool = LOGS_TOOLS['logs-attribute-values-list']!()

        // The logs backend reads these with json.loads(), so the handler must
        // NOT comma-join them — the client JSON-stringifies them on the wire.
        await tool.handler(context, { key: 'level', serviceNames: ['api', 'web'] })

        const call = request.mock.calls[0]![0] as RequestArgs
        expect(call.query?.serviceNames).toEqual(['api', 'web'])
    })
})

describe('ApiClient.request query serialization', () => {
    async function requestUrl(query: Record<string, unknown>): Promise<string> {
        const mockFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
        vi.stubGlobal('fetch', mockFetch)
        const client = new ApiClient({ apiToken: 'token', baseUrl: 'https://example.com' })
        await client.request({ method: 'GET', path: '/api/test/', query })
        return mockFetch.mock.calls[0]![0] as string
    }

    it('passes pre-joined CSV strings through verbatim', async () => {
        const url = await requestUrl({ type: 'internal_destination,transformation' })
        expect(url).toBe('https://example.com/api/test/?type=internal_destination%2Ctransformation')
    })

    it('JSON-stringifies arrays and objects for json.loads()-style backends', async () => {
        const url = await requestUrl({ serviceNames: ['api'], dateRange: { date_from: '-7d' } })
        const params = new URL(url).searchParams
        expect(params.get('serviceNames')).toBe('["api"]')
        expect(params.get('dateRange')).toBe('{"date_from":"-7d"}')
    })
})
