import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { createQueryWrapper } from '@/tools/query-wrapper-factory'
import type { Context } from '@/tools/types'
import { POSTHOG_META_KEY } from '@/tools/types'

describe('createQueryWrapper _meta', () => {
    const schema = z.object({ kind: z.string() })

    it('sets responseFormat in _meta when provided', () => {
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TestQuery', responseFormat: 'json' })

        const tool = factory()
        expect(tool._meta![POSTHOG_META_KEY]!.responseFormat).toBe('json')
    })

    it('omits responseFormat from _meta when not provided', () => {
        const factory = createQueryWrapper({ name: 'test', schema, kind: 'TestQuery' })

        const tool = factory()
        expect(tool._meta?.[POSTHOG_META_KEY]?.responseFormat).toBeUndefined()
    })

    it('sets both uiResourceUri and responseFormat in _meta', () => {
        const factory = createQueryWrapper({
            name: 'test',
            schema,
            kind: 'TestQuery',
            uiResourceUri: 'ui://posthog/test.html',
            responseFormat: 'json',
        })

        const tool = factory()
        expect(tool._meta).toEqual({
            ui: { resourceUri: 'ui://posthog/test.html' },
            [POSTHOG_META_KEY]: { responseFormat: 'json' },
        })
    })
})

describe('createQueryWrapper _posthogUrl', () => {
    const schema = z.object({
        series: z.array(z.object({ kind: z.string(), event: z.string() })),
    })

    function createMockContext(projectId = '1', baseUrl = 'http://localhost:8010'): Context {
        return {
            api: {
                query: vi.fn().mockReturnValue({
                    runQuery: vi.fn().mockResolvedValue({ results: [] }),
                    trendsActors: vi.fn().mockResolvedValue({
                        query: {},
                        results: { columns: [], results: [] },
                        hasMore: false,
                        offset: 0,
                    }),
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
