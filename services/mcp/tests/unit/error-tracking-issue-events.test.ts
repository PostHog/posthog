import { describe, expect, it, vi } from 'vitest'

import queryIssueEvents from '@/tools/errorTracking/queryIssueEvents'
import type { Context } from '@/tools/types'

function createMockContext(runQueryMock: ReturnType<typeof vi.fn>): Context {
    return {
        api: {
            query: vi.fn().mockReturnValue({
                runQuery: runQueryMock,
            }),
            getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
    } as unknown as Context
}

describe('query-error-tracking-issue-events', () => {
    const issueId = '00000000-0000-0000-0000-000000000000'

    it('builds a scoped EventsQuery and maps selected event properties', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            columns: [
                'uuid',
                'timestamp',
                'distinct_id',
                'properties.$exception_types',
                'properties.$exception_values',
                'properties.$exception_list',
                'properties.$session_id',
                'properties.$current_url',
            ],
            results: [
                [
                    'event-uuid',
                    '2026-04-24T12:00:00Z',
                    'user-1',
                    JSON.stringify(['TypeError']),
                    JSON.stringify(['Cannot read properties of undefined']),
                    JSON.stringify([
                        {
                            type: 'TypeError',
                            value: 'Cannot read properties of undefined',
                            raw_id: 'exception-raw-id',
                            junk_drawer: { sdk: 'noise' },
                            stacktrace: {
                                frames: [
                                    {
                                        filename: 'https://example.test/app.js',
                                        function: 'loadIssue',
                                        lineno: 42,
                                        colno: 9,
                                        in_app: true,
                                        raw_id: 'frame-raw-id',
                                        junk_drawer: { minified: true },
                                    },
                                ],
                            },
                            noisy_extra: 'drop me',
                        },
                    ]),
                    'session-id-1',
                    'https://example.test/app',
                ],
            ],
            hasMore: true,
            limit: 1,
            offset: 0,
        })
        const context = createMockContext(runQuery)
        const tool = queryIssueEvents()

        const filterGroup = [{ type: 'event' as const, key: '$browser', operator: 'exact' as const, value: ['Chrome'] }]
        const result = (await tool.handler(context, { issueId, searchQuery: "can't_load%_\\path", filterGroup })) as any
        const query = runQuery.mock.calls[0]![0].query

        expect(query).toMatchObject({
            kind: 'EventsQuery',
            event: '$exception',
            filterTestAccounts: true,
            after: '-7d',
            orderBy: ['timestamp DESC'],
            limit: 1,
            offset: 0,
            tags: { productKey: 'error_tracking' },
        })
        expect(query.properties).toEqual(filterGroup)
        expect(query.select).toContain('properties.$exception_types')
        expect(query.select).toContain('properties.$exception_values')
        expect(query.select).toContain('properties.$exception_list')
        expect(query.select).toContain('properties.$session_id')
        expect(query.where[0]).toContain(`issue_id = '${issueId}'`)
        expect(query.where[1]).toContain('properties.$exception_values')
        expect(query.where[1]).toContain("can\\'t\\\\_load\\\\%\\\\_\\\\\\\\path")
        expect(result).toEqual({
            results: [
                {
                    uuid: 'event-uuid',
                    timestamp: '2026-04-24T12:00:00Z',
                    distinct_id: 'user-1',
                    properties: {
                        $exception_types: ['TypeError'],
                        $exception_values: ['Cannot read properties of undefined'],
                        $exception_list: [
                            {
                                type: 'TypeError',
                                value: 'Cannot read properties of undefined',
                            },
                        ],
                        $session_id: 'session-id-1',
                        $current_url: 'https://example.test/app',
                    },
                },
            ],
            hasMore: true,
            limit: 1,
            offset: 0,
            nextOffset: 1,
            _posthogUrl: `http://localhost:8010/project/1/error_tracking/${issueId}`,
        })
    })

    it('caps limit at twenty through schema validation', async () => {
        const context = createMockContext(vi.fn())
        const tool = queryIssueEvents()

        await expect(tool.handler(context, { issueId, limit: 21 })).rejects.toThrow()
    })

    it('truncates long exception text outside raw mode', async () => {
        const longText = 'x'.repeat(1200)
        const runQuery = vi.fn().mockResolvedValue({
            columns: ['uuid', 'properties.$exception_values', 'properties.$exception_list'],
            results: [
                [
                    'event-uuid',
                    JSON.stringify([longText]),
                    JSON.stringify([
                        {
                            type: 'Error',
                            value: longText,
                            stacktrace: { frames: [] },
                        },
                    ]),
                ],
            ],
        })
        const context = createMockContext(runQuery)
        const tool = queryIssueEvents()

        const summaryResult = (await tool.handler(context, { issueId })) as any
        const stackResult = (await tool.handler(context, { issueId, verbosity: 'stack' })) as any
        const rawResult = (await tool.handler(context, { issueId, verbosity: 'raw' })) as any

        const truncatedValue = summaryResult.results[0].properties.$exception_values[0]
        expect(truncatedValue).toContain('[truncated from 1200 chars]')
        expect(truncatedValue.length).toBeLessThanOrEqual(1000)
        expect(summaryResult.results[0].properties.$exception_list[0].value).toContain('[truncated from 1200 chars]')
        expect(stackResult.results[0].properties.$exception_list[0].value).toContain('[truncated from 1200 chars]')
        expect(rawResult.results[0].properties.$exception_values[0]).toBe(longText)
        expect(rawResult.results[0].properties.$exception_list[0].value).toBe(longText)
    })

    it('returns parsed stack frames only when requested and filters vendor frames by default', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            columns: ['uuid', 'properties.$exception_list'],
            results: [
                [
                    'event-uuid',
                    JSON.stringify([
                        {
                            type: 'TypeError',
                            value: 'Cannot read properties of undefined',
                            noisy_extra: 'keep only in raw mode',
                            raw_id: 'exception-raw-id',
                            junk_drawer: { sdk: 'noise' },
                            stacktrace: {
                                raw_id: 'stacktrace-raw-id',
                                junk_drawer: { parser: 'noise' },
                                frames: [
                                    {
                                        filename: 'https://cdn.example.test/vendor.js',
                                        function: 'vendorLoad',
                                        lineno: 12,
                                        colno: 3,
                                        in_app: false,
                                        raw_id: 'vendor-frame-raw-id',
                                        junk_drawer: { minified: true },
                                    },
                                    {
                                        filename: 'https://example.test/app.js',
                                        function: 'loadIssue',
                                        lineno: 42,
                                        colno: 9,
                                        in_app: true,
                                        raw_id: 'app-frame-raw-id',
                                        junk_drawer: { minified: true },
                                    },
                                ],
                            },
                        },
                    ]),
                ],
            ],
        })
        const context = createMockContext(runQuery)
        const tool = queryIssueEvents()

        const stackResult = (await tool.handler(context, { issueId, verbosity: 'stack' })) as any
        const rawResult = (await tool.handler(context, { issueId, verbosity: 'raw', onlyAppFrames: false })) as any

        expect(stackResult.results[0].properties.$exception_list[0]).toEqual({
            type: 'TypeError',
            value: 'Cannot read properties of undefined',
            stacktrace: {
                frames: [
                    {
                        filename: 'https://example.test/app.js',
                        function: 'loadIssue',
                        lineno: 42,
                        colno: 9,
                        in_app: true,
                        source: 'https://example.test/app.js',
                        mangled_name: 'loadIssue',
                        line: 42,
                        column: 9,
                    },
                ],
            },
        })
        expect(rawResult.results[0].properties.$exception_list[0].noisy_extra).toBe('keep only in raw mode')
        expect(rawResult.results[0].properties.$exception_list[0].raw_id).toBe('exception-raw-id')
        expect(rawResult.results[0].properties.$exception_list[0].junk_drawer).toEqual({ sdk: 'noise' })
        expect(rawResult.results[0].properties.$exception_list[0].stacktrace.raw_id).toBe('stacktrace-raw-id')
        expect(rawResult.results[0].properties.$exception_list[0].stacktrace.junk_drawer).toEqual({
            parser: 'noise',
        })
        expect(rawResult.results[0].properties.$exception_list[0].stacktrace.frames).toHaveLength(2)
        expect(rawResult.results[0].properties.$exception_list[0].stacktrace.frames[0].raw_id).toBe(
            'vendor-frame-raw-id'
        )
        expect(rawResult.results[0].properties.$exception_list[0].stacktrace.frames[0].junk_drawer).toEqual({
            minified: true,
        })
    })

    it('trims limit-plus-one backend event pages to the requested limit', async () => {
        const runQuery = vi.fn().mockResolvedValue({
            columns: ['uuid'],
            results: [['event-1'], ['event-2']],
        })
        const context = createMockContext(runQuery)
        const tool = queryIssueEvents()

        const result = (await tool.handler(context, { issueId, limit: 1 })) as any

        expect(result.results).toEqual([{ uuid: 'event-1', properties: {} }])
        expect(result.hasMore).toBe(true)
        expect(result.limit).toBe(1)
        expect(result.nextOffset).toBe(1)
    })
})
