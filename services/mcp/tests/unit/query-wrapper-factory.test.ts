import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import type { Context } from '@/tools/types'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_META_KEY } from '@/tools/types'

describe('createQueryWrapper _meta', () => {
    const schema = z.object({ kind: z.string() })

    it.each(['optimized', 'json'] as const)('sets outputFormat %s in _meta when provided', (value) => {
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TestQuery', outputFormat: value })

        const tool = factory()
        expect(tool._meta![POSTHOG_META_KEY]!.outputFormat).toBe(value)
    })

    it('omits outputFormat from _meta when not provided', () => {
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TestQuery' })

        const tool = factory()
        expect(tool._meta?.[POSTHOG_META_KEY]?.outputFormat).toBeUndefined()
    })

    it('sets both uiResourceUri and outputFormat in _meta', () => {
        const factory = createQueryWrapper({
            name: 'test',
            schema,
            kind: 'TestQuery',
            uiResourceUri: 'ui://posthog/test.html',
            outputFormat: 'json',
        })

        const tool = factory()
        expect(tool._meta).toEqual({
            ui: { resourceUri: 'ui://posthog/test.html' },
            [POSTHOG_META_KEY]: { outputFormat: 'json' },
        })
    })
})

describe('createQueryWrapper _posthogUrl', () => {
    const schema = z.object({
        series: z.array(z.object({ kind: z.string(), event: z.string() })),
    })

    function createMockContext(
        projectId = '1',
        baseUrl = 'http://localhost:8010',
        query: Record<string, unknown> = {}
    ): Context {
        const actorsResponse = {
            query,
            results: { columns: [], results: [] },
            hasMore: false,
            offset: 0,
        }
        return {
            api: {
                query: vi.fn().mockReturnValue({
                    runQuery: vi.fn().mockResolvedValue({ results: [] }),
                    trendsActors: vi.fn().mockResolvedValue(actorsResponse),
                    lifecycleActors: vi.fn().mockResolvedValue(actorsResponse),
                }),
                getProjectBaseUrl: vi.fn().mockReturnValue(`${baseUrl}/project/${projectId}`),
            },
            stateManager: {
                getProjectId: vi.fn().mockResolvedValue(projectId),
            },
        } as unknown as Context
    }

    it.each(['TrendsQuery', 'FunnelsQuery', 'RetentionQuery', 'StickinessQuery', 'PathsQuery', 'LifecycleQuery'])(
        'wraps %s in InsightVizNode in the URL',
        async (kind) => {
            const context = createMockContext()
            const factory = createQueryWrapper({ name: 'test', schema, kind })
            const tool = factory()

            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
            })) as any

            const hash = result._posthogUrl.split('#q=')[1]
            expect(hash).toBeTruthy()
            const parsed = JSON.parse(decodeURIComponent(hash))
            expect(parsed.kind).toBe('InsightVizNode')
            expect(parsed.source.kind).toBe(kind)
        }
    )

    function createActorsDispatchContext(): {
        context: Context
        trendsActors: ReturnType<typeof vi.fn>
        lifecycleActors: ReturnType<typeof vi.fn>
        pathsActors: ReturnType<typeof vi.fn>
        retentionActors: ReturnType<typeof vi.fn>
        stickinessActors: ReturnType<typeof vi.fn>
        funnelActors: ReturnType<typeof vi.fn>
    } {
        const actorsResponse = {
            query: { kind: 'ActorsQuery', source: { kind: 'InsightActorsQuery' } },
            results: { columns: [], results: [] },
            hasMore: false,
            offset: 0,
        }
        const trendsActors = vi.fn().mockResolvedValue(actorsResponse)
        const lifecycleActors = vi.fn().mockResolvedValue(actorsResponse)
        const pathsActors = vi.fn().mockResolvedValue(actorsResponse)
        const retentionActors = vi.fn().mockResolvedValue(actorsResponse)
        const stickinessActors = vi.fn().mockResolvedValue(actorsResponse)
        const funnelActors = vi.fn().mockResolvedValue(actorsResponse)
        const context = {
            api: {
                query: vi.fn().mockReturnValue({
                    trendsActors,
                    lifecycleActors,
                    pathsActors,
                    retentionActors,
                    stickinessActors,
                    funnelActors,
                }),
                getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
        } as unknown as Context
        return { context, trendsActors, lifecycleActors, pathsActors, retentionActors, stickinessActors, funnelActors }
    }

    const actorsSchema = z.object({
        day: z.string().optional(),
        source: z.looseObject({ kind: z.string() }),
    })

    const ACTOR_HANDLERS = [
        'trendsActors',
        'lifecycleActors',
        'pathsActors',
        'retentionActors',
        'stickinessActors',
        'funnelActors',
    ] as const

    it.each([
        ['TrendsQuery', 'trendsActors'],
        ['LifecycleQuery', 'lifecycleActors'],
        ['PathsQuery', 'pathsActors'],
        ['RetentionQuery', 'retentionActors'],
        ['StickinessQuery', 'stickinessActors'],
        ['FunnelsQuery', 'funnelActors'],
    ] as const)('dispatches %s source to %s and no other handler', async (sourceKind, expectedHandler) => {
        const ctx = createActorsDispatchContext()
        const tool = createQueryWrapper({ name: 'test', schema: actorsSchema, kind: 'InsightActorsQuery' })()

        const result = (await tool.handler(ctx.context, { source: { kind: sourceKind } })) as any

        for (const handler of ACTOR_HANDLERS) {
            expect(ctx[handler]).toHaveBeenCalledTimes(handler === expectedHandler ? 1 : 0)
        }
        expect(result._posthogUrl).toContain('DataTableNode')
    })

    it('uses hash param not query param', async () => {
        const context = createMockContext()
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TrendsQuery' })
        const tool = factory()

        const result = (await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
        })) as any

        expect(result._posthogUrl).toContain('/insights/new#q=')
        expect(result._posthogUrl).not.toContain('/insights/new?q=')
    })

    it('preserves inner query fields in InsightVizNode source', async () => {
        const context = createMockContext()
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'FunnelsQuery' })
        const tool = factory()

        const result = (await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
        })) as any

        const hash = result._posthogUrl.split('#q=')[1]
        const parsed = JSON.parse(decodeURIComponent(hash))
        expect(parsed.kind).toBe('InsightVizNode')
        expect(parsed.source.kind).toBe('FunnelsQuery')
        expect(parsed.source.series).toEqual([{ kind: 'EventsNode', event: '$pageview' }])
    })

    it('uses urlPrefix directly without InsightVizNode wrapping', async () => {
        const context = createMockContext()
        const factory = createQueryWrapper({
            name: 'test',
            schema,
            kind: 'ErrorTrackingQuery',
            urlPrefix: '/error_tracking',
        })
        const tool = factory()

        const result = (await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
        })) as any

        expect(result._posthogUrl).toBe('http://localhost:8010/project/1/error_tracking')
        expect(result._posthogUrl).not.toContain('InsightVizNode')
    })
})

describe('createQueryWrapper output_format handling', () => {
    const schemaWithOutputFormat = z.object({
        series: z.array(z.object({ kind: z.string(), event: z.string() })),
        output_format: z.enum(['optimized', 'json']).default('optimized').optional(),
    })

    function createMockContext(runQueryMock: ReturnType<typeof vi.fn>): Context {
        return {
            api: {
                query: vi.fn().mockReturnValue({
                    runQuery: runQueryMock,
                    trendsActors: vi.fn(),
                    lifecycleActors: vi.fn(),
                }),
                getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
        } as unknown as Context
    }

    it('strips output_format from the query body sent to the backend', async () => {
        const runQuery = vi.fn().mockResolvedValue({ results: [], formatted_results: null })
        const context = createMockContext(runQuery)
        const factory = createQueryWrapper({
            name: 'test',
            schema: schemaWithOutputFormat,
            kind: 'TrendsQuery',
            outputFormat: 'optimized',
        })
        const tool = factory()

        await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
            output_format: 'json',
        })

        const queryArg = runQuery.mock.calls[0]![0].query
        expect(queryArg.kind).toBe('TrendsQuery')
        expect(queryArg.output_format).toBeUndefined()
    })

    it('surfaces formatted_results by default when config outputFormat is optimized', async () => {
        const runQuery = vi.fn().mockResolvedValue({ results: [], formatted_results: 'formatted-text' })
        const context = createMockContext(runQuery)
        const factory = createQueryWrapper({
            name: 'test',
            schema: schemaWithOutputFormat,
            kind: 'TrendsQuery',
            outputFormat: 'optimized',
        })
        const tool = factory()

        const result = (await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
        })) as any

        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('formatted-text')
    })

    it('skips formatted_results when caller requests output_format: json', async () => {
        const runQuery = vi.fn().mockResolvedValue({ results: [], formatted_results: 'formatted-text' })
        const context = createMockContext(runQuery)
        const factory = createQueryWrapper({
            name: 'test',
            schema: schemaWithOutputFormat,
            kind: 'TrendsQuery',
            outputFormat: 'optimized',
        })
        const tool = factory()

        const result = (await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
            output_format: 'json',
        })) as any

        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBeUndefined()
    })

    it('surfaces formatted_results when caller overrides config json with optimized', async () => {
        const runQuery = vi.fn().mockResolvedValue({ results: [], formatted_results: 'formatted-text' })
        const context = createMockContext(runQuery)
        const factory = createQueryWrapper({
            name: 'test',
            schema: schemaWithOutputFormat,
            kind: 'TrendsQuery',
            outputFormat: 'json',
        })
        const tool = factory()

        const result = (await tool.handler(context, {
            series: [{ kind: 'EventsNode', event: '$pageview' }],
            output_format: 'optimized',
        })) as any

        expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('formatted-text')
    })
})

describe('createQueryWrapper actors dispatch', () => {
    function createMockContext(): Context {
        return {
            api: {
                query: vi.fn().mockReturnValue({
                    runQuery: vi.fn(),
                    trendsActors: vi.fn(),
                    lifecycleActors: vi.fn(),
                    pathsActors: vi.fn(),
                }),
                getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
            },
            stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
        } as unknown as Context
    }

    it('throws when actors source kind is not supported', async () => {
        const context = createMockContext()
        const actorsSchema = z.object({
            source: z.looseObject({ kind: z.string() }),
        })
        const factory = createQueryWrapper({ name: 'test', schema: actorsSchema, kind: 'InsightActorsQuery' })
        const tool = factory()

        await expect(tool.handler(context, { source: { kind: 'FunnelCorrelationQuery' } })).rejects.toThrow(
            'Unsupported source kind for actors query: FunnelCorrelationQuery'
        )
    })
})
