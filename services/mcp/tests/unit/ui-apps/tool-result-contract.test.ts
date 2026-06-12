import { describe, expect, it, vi } from 'vitest'

import { buildToolResultPayload, type ToolResultMeta } from '@/lib/build-tool-result'
import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'
import insightQueryTool from '@/tools/insights/query'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context } from '@/tools/types'
import { inferVisualizationType } from '@/ui-apps/components/infer-visualization'
import { toActorRows, type InsightActorsData } from 'products/product_analytics/mcp/apps/insightActorsTransforms'

import { insightResults } from '../../fixtures/insight-fixtures'

// Contract tests for the seam the UI apps depend on: tool handler → buildToolResultPayload →
// `structuredContent` → visualization dispatch. The unit tests around inferVisualizationType
// validate the dispatcher in isolation; these validate that what the real tools put into
// `structuredContent` is something the dispatcher (and visualizers) can actually consume.

const FORMATTED_TEXT = 'Formatted summary for the model'

function createQueryContext(queryResponse: Record<string, unknown>): Context {
    return {
        api: {
            query: vi.fn().mockReturnValue({
                runQuery: vi.fn().mockResolvedValue(queryResponse),
                trendsActors: vi.fn().mockResolvedValue(queryResponse),
                lifecycleActors: vi.fn().mockResolvedValue(queryResponse),
                pathsActors: vi.fn().mockResolvedValue(queryResponse),
            }),
            getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
        },
        stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
    } as unknown as Context
}

async function runGeneratedTool(
    name: string,
    params: Record<string, unknown>,
    queryResponse: Record<string, unknown>,
    options: { suppressStructuredContent?: boolean } = {}
): Promise<ReturnType<typeof buildToolResultPayload>> {
    const tool = GENERATED_TOOLS[name]!()
    const handlerResult = await tool.handler(createQueryContext(queryResponse), params)
    return buildToolResultPayload({
        handlerResult,
        toolMeta: tool._meta as ToolResultMeta,
        toolName: tool.name,
        params,
        suppressStructuredContentForFormattedResults: options.suppressStructuredContent ?? false,
        distinctId: 'user-1',
    })
}

const series = [{ event: '$pageview' }]
const retentionEntity = { id: '$pageview', type: 'events' }

describe('tool result → UI app contract', () => {
    describe('query wrappers feeding the query-results app', () => {
        it.each([
            ['query-trends', { series }, insightResults.trendsLine, 'trends'],
            [
                'query-funnel',
                { series: [{ event: '$pageview' }, { event: 'sign_up' }] },
                insightResults.funnelTopToBottom,
                'funnel',
            ],
            [
                'query-retention',
                { retentionFilter: { targetEntity: retentionEntity, returningEntity: retentionEntity } },
                insightResults.retention,
                'retention',
            ],
            ['query-stickiness', { series }, insightResults.stickiness, 'trends'],
            ['query-paths', { pathsFilter: {} }, insightResults.userPaths, 'paths'],
            ['query-lifecycle', { series }, insightResults.lifecycle, 'lifecycle'],
        ] as const)(
            '%s produces structuredContent the UI app can classify',
            async (name, params, results, expected) => {
                const payload = await runGeneratedTool(name, params, {
                    results,
                    formatted_results: FORMATTED_TEXT,
                })

                // The model reads the formatted text; the UI app reads structuredContent.
                expect(payload.content[0]!.text).toBe(FORMATTED_TEXT)
                const structuredContent = payload.structuredContent!
                expect(structuredContent).not.toBeUndefined()
                // The override key is transport plumbing — it must never reach the iframe.
                expect(structuredContent[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBeUndefined()
                // Raw results (not the formatted string) flow to the UI app...
                expect(typeof structuredContent.results).not.toBe('string')
                // ...and classify to the visualizer the app will render.
                expect(inferVisualizationType(structuredContent)).toBe(expected)
                expect(structuredContent._analytics).toEqual({ distinctId: 'user-1', toolName: name })
            }
        )

        it('still ships classifiable structuredContent when the backend has no formatter output', async () => {
            const payload = await runGeneratedTool('query-trends', { series }, { results: insightResults.trendsLine })

            expect(payload.structuredContent).not.toBeUndefined()
            expect(inferVisualizationType(payload.structuredContent)).toBe('trends')
        })

        it('drops structuredContent for clients that surface it to the model (coding agents)', async () => {
            const payload = await runGeneratedTool(
                'query-trends',
                { series },
                { results: insightResults.trendsLine, formatted_results: FORMATTED_TEXT },
                { suppressStructuredContent: true }
            )

            expect(payload.content[0]!.text).toBe(FORMATTED_TEXT)
            expect(payload.structuredContent).toBeUndefined()
        })
    })

    describe('actors wrappers feeding the insight-actors app', () => {
        it('query-trends-actors produces structuredContent toActorRows can consume', async () => {
            const actorsResponse = {
                query: { kind: 'ActorsQuery', source: { kind: 'InsightActorsQuery' } },
                results: {
                    columns: ['distinct_id', 'email', 'event_count'],
                    results: [['d1', 'a@b.com', 7]],
                },
                hasMore: false,
                offset: 0,
            }
            const payload = await runGeneratedTool(
                'query-trends-actors',
                { day: '2025-06-01', source: { series } },
                actorsResponse
            )

            const structuredContent = payload.structuredContent!
            expect(structuredContent).not.toBeUndefined()
            const rows = toActorRows(structuredContent as unknown as InsightActorsData)
            expect(rows).toHaveLength(1)
            expect(rows[0]!.email).toBe('a@b.com')
            expect(rows[0]!.event_count).toBe(7)
        })
    })

    describe('insight-query feeding the query-results app', () => {
        function createInsightContext(query: Record<string, unknown>, queryData: Record<string, unknown>): Context {
            return {
                api: {
                    insights: vi.fn().mockReturnValue({
                        get: vi.fn().mockResolvedValue({
                            success: true,
                            data: { id: 42, short_id: 'abc12345', name: 'My insight', query },
                        }),
                        query: vi.fn().mockResolvedValue({ success: true, data: queryData }),
                    }),
                    getProjectBaseUrl: vi.fn().mockReturnValue('http://localhost:8010/project/1'),
                },
                stateManager: { getProjectId: vi.fn().mockResolvedValue('1') },
            } as unknown as Context
        }

        const trendsVizQuery = {
            kind: 'InsightVizNode',
            source: { kind: 'TrendsQuery', series: [{ event: '$pageview' }] },
        }

        it('with output_format=json ships raw results the UI app can classify', async () => {
            const tool = insightQueryTool()
            const context = createInsightContext(trendsVizQuery, { results: insightResults.trendsLine })
            const params = { insightId: '42', output_format: 'json' as const }

            const handlerResult = await tool.handler(context, params)
            const payload = buildToolResultPayload({
                handlerResult,
                toolMeta: tool._meta as ToolResultMeta,
                toolName: tool.name,
                params,
                suppressStructuredContentForFormattedResults: false,
                distinctId: 'user-1',
            })

            const structuredContent = payload.structuredContent!
            expect(structuredContent).not.toBeUndefined()
            expect(typeof structuredContent.results).not.toBe('string')
            expect(inferVisualizationType(structuredContent)).toBe('trends')
        })

        it('with output_format=optimized (the default) sends a formatted string into the UI app', async () => {
            // BUG PIN: unlike the query wrappers, insight-query puts `formatted_results` (a string)
            // directly into `results` instead of using the override key, so the query-results app
            // receives a string where every visualizer expects arrays. Classification only works
            // via the query-kind fallback, and the visualizer then crashes on `results.map`.
            // Flip these assertions when insight-query adopts the wrapper pattern.
            const tool = insightQueryTool()
            const context = createInsightContext(trendsVizQuery, {
                results: insightResults.trendsLine,
                formatted_results: FORMATTED_TEXT,
            })
            const params = { insightId: '42', output_format: 'optimized' as const }

            const handlerResult = await tool.handler(context, params)
            const payload = buildToolResultPayload({
                handlerResult,
                toolMeta: tool._meta as ToolResultMeta,
                toolName: tool.name,
                params,
                suppressStructuredContentForFormattedResults: false,
                distinctId: 'user-1',
            })

            const structuredContent = payload.structuredContent!
            expect(structuredContent).not.toBeUndefined()
            expect(typeof structuredContent.results).toBe('string')
            expect(inferVisualizationType(structuredContent)).toBe('trends')
        })
    })
})
