import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import type { ApiClient } from '@/api/client'
import type { InsightQuery } from '@/schema/query'
import queryRunTool from '@/tools/query/run'
import type { Context } from '@/tools/types'

import {
    type CreatedResources,
    SAMPLE_FUNNEL_QUERIES,
    SAMPLE_HOGQL_QUERIES,
    SAMPLE_TREND_QUERIES,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '../shared/test-utils'

/**
 * Helper to execute a query and log detailed debug info on failure
 */
async function executeQuery(context: Context, query: InsightQuery, queryName: string): Promise<any> {
    const tool = queryRunTool()
    try {
        const result = await tool.handler(context, { query })
        return result
    } catch (error: any) {
        console.error(`[TEST] ${queryName} query FAILED:`)
        console.error(`[TEST]   Error: ${error.message}`)
        console.error(`[TEST]   Query: ${JSON.stringify(query, null, 2)}`)
        throw error
    }
}

/**
 * Asserts the common structure of a query response and returns typed results
 */
function assertQueryResponse(response: any, expectedQueryKind?: string): { results: any; query: any; url: string } {
    expect(response).toHaveProperty('query')
    expect(response).toHaveProperty('results')
    expect(response).toHaveProperty('_posthogUrl')
    expect(typeof response._posthogUrl).toBe('string')
    expect(response._posthogUrl).toMatch(/\/insights\/new\?q=/)

    if (expectedQueryKind) {
        expect(response.query.kind).toBe(expectedQueryKind)
    }

    return { results: response.results, query: response.query, url: response._posthogUrl }
}

/**
 * Asserts HogQL query response structure (has columns and nested results)
 */
function assertHogQLResults(results: any): { columns: string[]; rows: any[][] } {
    expect(results).toHaveProperty('columns')
    expect(results).toHaveProperty('results')
    expect(Array.isArray(results.columns)).toBe(true)
    expect(Array.isArray(results.results)).toBe(true)

    // Columns should be strings
    results.columns.forEach((col: any) => expect(typeof col).toBe('string'))
    return { columns: results.columns, rows: results.results }
}

/**
 * Asserts Trends/Funnel query response structure (results is direct array)
 */
function assertSeriesResults(results: any): any[] {
    expect(Array.isArray(results)).toBe(true)
    return results
}

describe('Query Integration Tests', () => {
    let client: ApiClient
    let context: Context
    let testProjectId: string
    let testOrgId: string
    let createdResources: CreatedResources

    beforeAll(async () => {
        validateEnvironmentVariables()
        client = createTestClient()
        context = createTestContext(client)
        testProjectId = TEST_PROJECT_ID!
        testOrgId = TEST_ORG_ID!

        await setActiveProjectAndOrg(context, testProjectId, testOrgId)

        createdResources = {
            featureFlags: [],
            insights: [],
            dashboards: [],
            surveys: [],
            actions: [],
        }
    })

    afterEach(async () => {
        await cleanupResources(client, testProjectId, createdResources)
    })

    describe('HogQL Query Execution', () => {
        it('should execute pageviews HogQL query successfully', async () => {
            const result = await executeQuery(context, SAMPLE_HOGQL_QUERIES.pageviews, 'pageviews HogQL')
            const { results } = assertQueryResponse(result)
            const { columns } = assertHogQLResults(results)

            // Should have event and count columns based on the query
            expect(columns).toContain('event')
            expect(columns).toContain('event_count')
        })

        it('should execute topEvents HogQL query successfully', async () => {
            const result = await executeQuery(context, SAMPLE_HOGQL_QUERIES.topEvents, 'topEvents HogQL')
            const { results } = assertQueryResponse(result)
            const { columns } = assertHogQLResults(results)

            // Should have event and count columns based on the query
            expect(columns).toContain('event')
            expect(columns).toContain('event_count')
        })

        it('should handle invalid HogQL query with invalid node', async () => {
            const invalidQuery = {
                kind: 'DataVisualizationNode' as const,
                source: {
                    kind: 'HogQLQuery' as const,
                    query: "SELECT * FROM invalid_table WHERE invalid_column = 'test'",
                    filters: {
                        dateRange: {
                            date_from: '-7d',
                            date_to: null,
                        },
                    },
                },
            }

            const tool = queryRunTool()

            try {
                await tool.handler(context, {
                    query: invalidQuery,
                })
            } catch (error: any) {
                expect(error).toBeTruthy()
                expect(error.message).toContain('Failed to query insight')
            }
        })
    })

    describe('Trends Query Execution', () => {
        it('should execute basic pageviews trends query successfully', async () => {
            const result = await executeQuery(context, SAMPLE_TREND_QUERIES.basicPageviews, 'basicPageviews Trends')
            const { results, query } = assertQueryResponse(result, 'TrendsQuery')
            const series = assertSeriesResults(results)

            // Trends results should have series data with labels and counts
            if (series.length > 0) {
                expect(series[0]).toHaveProperty('label')
                expect(series[0]).toHaveProperty('count')
                expect(series[0]).toHaveProperty('data')
            }

            // Query should preserve the series configuration
            expect(query.series).not.toBeUndefined()
            expect(query.series[0].event).toBe('$pageview')
        })

        it('should execute unique users trends query successfully', async () => {
            const query = SAMPLE_TREND_QUERIES.uniqueUsers

            const result = await executeQuery(context, query, 'uniqueUsers Trends')
            const { results, query: queryResponse } = assertQueryResponse(result, 'TrendsQuery')
            assertSeriesResults(results)

            // Should use DAU math
            expect(queryResponse.series[0].math).toBe(query.source.series[0].math)
        })

        it('should execute multiple events trends query successfully', async () => {
            const query = SAMPLE_TREND_QUERIES.multipleEvents

            const result = await executeQuery(context, query, 'multipleEvents Trends')
            const { results, query: queryResponse } = assertQueryResponse(result, 'TrendsQuery')
            assertSeriesResults(results)

            // Should have multiple series in the query
            expect(queryResponse.series.length).toBe(query.source.series.length)
        })

        it('should execute trends query with breakdown successfully', async () => {
            const query = SAMPLE_TREND_QUERIES.withBreakdown
            const result = await executeQuery(context, query, 'withBreakdown Trends')
            const { results, query: queryResponse } = assertQueryResponse(result, 'TrendsQuery')
            assertSeriesResults(results)

            // Should have breakdown configuration
            expect(queryResponse.breakdownFilter).not.toBeUndefined()
            expect(queryResponse.breakdownFilter.breakdown).toBe(query.source.breakdownFilter.breakdown)
        })

        it('should execute trends query with property filter successfully', async () => {
            const query = SAMPLE_TREND_QUERIES.withPropertyFilter
            const result = await executeQuery(context, query, 'withPropertyFilter Trends')
            const { results, query: queryResponse } = assertQueryResponse(result, 'TrendsQuery')
            assertSeriesResults(results)

            // Should have property filters on the series
            expect(queryResponse.series[0].properties).not.toBeUndefined()
            expect(queryResponse.series[0].properties.length).toBeGreaterThan(0)
        })
    })

    describe('Funnel Query Execution', () => {
        it('should execute basic funnel query successfully', async () => {
            const query = SAMPLE_FUNNEL_QUERIES.basicFunnel

            const result = await executeQuery(context, query, 'basicFunnel')
            const { results, query: queryResponse } = assertQueryResponse(result, 'FunnelsQuery')
            assertSeriesResults(results)

            // Query should have the funnel steps
            expect(queryResponse.series).not.toBeUndefined()
            expect(queryResponse.series.length).toBe(query.source.series.length)
        })

        it('should execute strict order funnel query successfully', async () => {
            const query = SAMPLE_FUNNEL_QUERIES.strictOrderFunnel

            const result = await executeQuery(context, query, 'strictOrderFunnel')
            const { results, query: queryResponse } = assertQueryResponse(result, 'FunnelsQuery')
            assertSeriesResults(results)

            // Should have strict order configuration
            expect(queryResponse.funnelsFilter).not.toBeUndefined()
            expect(queryResponse.funnelsFilter.funnelOrderType).toBe(query.source.funnelsFilter.funnelOrderType)
        })

        it('should execute funnel with breakdown query successfully', async () => {
            const query = SAMPLE_FUNNEL_QUERIES.funnelWithBreakdown

            const result = await executeQuery(context, query, 'funnelWithBreakdown')
            const { results, query: queryResponse } = assertQueryResponse(result, 'FunnelsQuery')
            assertSeriesResults(results)

            // Should have breakdown configuration
            expect(queryResponse.breakdownFilter).not.toBeUndefined()
            expect(queryResponse.breakdownFilter.breakdown).toBe(query.source.breakdownFilter.breakdown)
        })

        it('should execute funnel with conversion window query successfully', async () => {
            const query = SAMPLE_FUNNEL_QUERIES.conversionWindow

            const result = await executeQuery(context, query, 'conversionWindow')
            const { results, query: queryResponse } = assertQueryResponse(result, 'FunnelsQuery')
            assertSeriesResults(results)

            // Should have custom conversion window (1 hour)
            expect(queryResponse.funnelsFilter).not.toBeUndefined()
            expect(queryResponse.funnelsFilter.funnelWindowInterval).toBe(
                query.source.funnelsFilter.funnelWindowInterval
            )
            expect(queryResponse.funnelsFilter.funnelWindowIntervalUnit).toBe(
                query.source.funnelsFilter.funnelWindowIntervalUnit
            )
        })

        it('should execute onboarding funnel query successfully', async () => {
            const query = SAMPLE_FUNNEL_QUERIES.onboardingFunnel

            const result = await executeQuery(context, query, 'onboardingFunnel')
            const { results, query: queryResponse } = assertQueryResponse(result, 'FunnelsQuery')
            assertSeriesResults(results)

            // Should have 4 steps in the onboarding funnel
            expect(queryResponse.series.length).toBe(query.source.series.length)
        })

        it('should handle malformed funnel query with invalid node', async () => {
            const malformedFunnel = {
                kind: 'InsightVizNode' as const,
                source: {
                    kind: 'FunnelsQuery' as const,
                    series: [
                        {
                            kind: 'InvalidNode' as const,
                            event: '$pageview',
                            custom_name: 'Single Step',
                        },
                    ],
                    dateRange: {
                        date_from: '-7d',
                        date_to: null,
                    },
                    properties: [],
                    filterTestAccounts: false,
                },
            }

            const tool = queryRunTool()

            try {
                await tool.handler(context, {
                    query: malformedFunnel as unknown as InsightQuery,
                })
            } catch (error: any) {
                expect(error).toBeTruthy()
            }
        })
    })
})
