import type { ApiClient } from '@/api/client'
import type { InsightQuery } from '@/schema/query'
import queryRunTool from '@/tools/query/run'
import type { Context } from '@/tools/types'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'
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
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '../shared/test-utils'

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
        }
    })

    afterEach(async () => {
        await cleanupResources(client, testProjectId, createdResources)
    })

    describe('HogQL Query Execution', () => {
        it('should execute pageviews HogQL query successfully', async () => {
            const tool = queryRunTool()
            const query = SAMPLE_HOGQL_QUERIES.pageviews
            const result = await tool.handler(context, {
                query,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute topEvents HogQL query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_HOGQL_QUERIES.topEvents,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
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
                expect(error).toBeDefined()
                expect(error.message).toContain('Failed to query insight')
            }
        })
    })

    describe('Trends Query Execution', () => {
        it('should execute basic pageviews trends query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_TREND_QUERIES.basicPageviews,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute unique users trends query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_TREND_QUERIES.uniqueUsers,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute multiple events trends query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_TREND_QUERIES.multipleEvents,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute trends query with breakdown successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_TREND_QUERIES.withBreakdown,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute trends query with property filter successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_TREND_QUERIES.withPropertyFilter,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })
    })

    describe('Funnel Query Execution', () => {
        it('should execute basic funnel query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_FUNNEL_QUERIES.basicFunnel,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute strict order funnel query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_FUNNEL_QUERIES.strictOrderFunnel,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute funnel with breakdown query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_FUNNEL_QUERIES.funnelWithBreakdown,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute funnel with conversion window query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_FUNNEL_QUERIES.conversionWindow,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
        })

        it('should execute onboarding funnel query successfully', async () => {
            const tool = queryRunTool()
            const result = await tool.handler(context, {
                query: SAMPLE_FUNNEL_QUERIES.onboardingFunnel,
            })

            const response = parseToolResponse(result)

            expect(result.content).toBeDefined()
            expect(result.content[0].type).toBe('text')
            expect(response).toBeDefined()
            expect(Array.isArray(response)).toBe(true)
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
                expect(error).toBeDefined()
            }
        })
    })
})
