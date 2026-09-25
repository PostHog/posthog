import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiClient } from '@/api/client'
import { buildToolResultPayload } from '@/lib/build-tool-result'
import { ExecuteSQLSchema } from '@/schema/tool-inputs'
import { executeSqlHandler } from '@/tools/posthogAiTools/executeSql'
import type { Context } from '@/tools/types'
import { APP_DATA_META_KEY } from '@/ui-apps/types'

describe('executeSqlHandler', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it.each([
        { structured: false, outputFormat: 'optimized' },
        { structured: true, outputFormat: 'optimized' },
        { structured: true, outputFormat: 'json' },
    ] as const)('preserves results and query metadata: %j', async ({ structured, outputFormat }) => {
        const query = {
            kind: 'HogQLQuery',
            query: 'SELECT {variables.org}',
            variables: { 'example-variable': { variableId: 'example-variable', code_name: 'org' } },
        }
        const content = 'org\nExample organization'
        vi.stubGlobal(
            'fetch',
            vi.fn().mockResolvedValue(
                new Response(
                    JSON.stringify({
                        success: true,
                        content,
                        ...(structured ? { structured_content: { query } } : {}),
                    })
                )
            )
        )
        const context = {
            api: new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' }),
            stateManager: { getProjectId: vi.fn().mockResolvedValue(2) },
        } as unknown as Context
        const params = { query: `${query.query};`, truncate: true, output_format: outputFormat }
        const handlerResult = await executeSqlHandler(context, params)

        for (const includeAppData of [false, true]) {
            const payload = buildToolResultPayload({ handlerResult, toolName: 'execute-sql', params, includeAppData })
            if (includeAppData && outputFormat === 'json') {
                expect(JSON.parse(payload.content[0]!.text)).toEqual({ query, results: content })
            } else {
                expect(payload.content).toEqual([{ type: 'text', text: content }])
            }
            expect(payload._meta?.[APP_DATA_META_KEY]).toEqual(
                structured && includeAppData ? { query, results: content } : undefined
            )
            expect(payload.structuredContent).toBeUndefined()
        }
    })

    // The catalog disclosure the metric-discovery prompt asks for has to have a field to
    // live in, and it has to stay on this side of the wire: the endpoint takes no such
    // argument, and the sentence is bookkeeping rather than part of the query.
    it('takes a query context and keeps it out of the upstream request', async () => {
        const fetchMock = vi
            .fn()
            .mockResolvedValue(new Response(JSON.stringify({ success: true, content: 'count\n1' })))
        vi.stubGlobal('fetch', fetchMock)
        const context = {
            api: new ApiClient({ apiToken: 'phx_test', baseUrl: 'https://us.posthog.com' }),
            stateManager: { getProjectId: vi.fn().mockResolvedValue(2) },
        } as unknown as Context

        const params = ExecuteSQLSchema.parse({
            query: 'SELECT count() FROM events WHERE timestamp > now() - INTERVAL 1 DAY',
            context: 'governed catalog consulted: no match',
        })
        await executeSqlHandler(context, params)

        expect(params.context).toBe('governed catalog consulted: no match')
        expect(fetchMock).toHaveBeenCalledOnce()
        expect(String(fetchMock.mock.calls[0]?.[1]?.body)).not.toContain('governed catalog consulted')
    })
})
