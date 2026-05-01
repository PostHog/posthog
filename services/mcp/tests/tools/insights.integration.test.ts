import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    SAMPLE_HOGQL_QUERIES,
    SAMPLE_TREND_QUERIES,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'
import queryInsightTool from '@/tools/insights/query'
import type { Context } from '@/tools/types'

const insightGetTool = GENERATED_TOOLS['insight-get']!()
const insightCreateTool = GENERATED_TOOLS['insight-create']!()
const insightUpdateTool = GENERATED_TOOLS['insight-update']!()
const insightDeleteTool = GENERATED_TOOLS['insight-delete']!()

describe('Insights', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    async function createTestInsight(name: string): Promise<{ id: number; short_id: string; name: string }> {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<{
            id: number
            short_id: string
            name: string
        }>({
            method: 'POST',
            path: `/api/projects/${projectId}/insights/`,
            body: {
                name,
                query: SAMPLE_HOGQL_QUERIES.pageviews,
                saved: true,
            },
        })
        createdResources.insights.push(result.id)
        return result
    }

    async function createTestTrendsInsight(name: string): Promise<{ id: number; short_id: string; name: string }> {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request<{
            id: number
            short_id: string
            name: string
        }>({
            method: 'POST',
            path: `/api/projects/${projectId}/insights/`,
            body: {
                name,
                query: SAMPLE_TREND_QUERIES.basicPageviews,
                saved: true,
            },
        })
        createdResources.insights.push(result.id)
        return result
    }

    describe('insight-query tool', () => {
        const queryTool = queryInsightTool()

        it('should run an insight and return optimized results by default', async () => {
            const insight = await createTestInsight(generateUniqueKey('Run Optimized Test'))

            const result = await queryTool.handler(context, {
                insightId: String(insight.id),
                output_format: 'optimized',
            })
            const response = parseToolResponse(result)

            expect(response).toHaveProperty('insight')
            expect(response).toHaveProperty('results')
            expect(response.insight.id).toBe(insight.id)
            expect(response.insight.name).toBe(insight.name)
            expect(response.insight.url).toContain('/insights/')
        })

        it('should run an insight and return JSON results when format is json', async () => {
            const insight = await createTestInsight(generateUniqueKey('Run JSON Test'))

            const result = await queryTool.handler(context, {
                insightId: String(insight.id),
                output_format: 'json',
            })
            const response = parseToolResponse(result)

            expect(response).toHaveProperty('insight')
            expect(response).toHaveProperty('results')
            expect(response.insight.id).toBe(insight.id)
        })

        it('should default to optimized format when format is not specified', async () => {
            const insight = await createTestInsight(generateUniqueKey('Run Default Format Test'))

            // Simulate what the MCP server does: parse input through the schema to apply defaults
            const parsedParams = queryTool.schema.parse({ insightId: String(insight.id) })
            const result = await queryTool.handler(context, parsedParams)
            const response = parseToolResponse(result)

            expect(response).toHaveProperty('insight')
            expect(response).toHaveProperty('results')
        })

        describe('result shapes by format and query type', () => {
            it('HogQL query with output_format=json returns table shape with columns and results arrays', async () => {
                const insight = await createTestInsight(generateUniqueKey('HogQL JSON Shape'))

                const result = await queryTool.handler(context, {
                    insightId: String(insight.id),
                    output_format: 'json',
                })
                const response = parseToolResponse(result)

                expect(response).toHaveProperty('results')
                expect(response.results).toHaveProperty('columns')
                expect(response.results).toHaveProperty('results')
                expect(Array.isArray(response.results.columns)).toBe(true)
                expect(Array.isArray(response.results.results)).toBe(true)
            })

            it('HogQL query with output_format=optimized returns a formatted string', async () => {
                // The API client always sends X-PostHog-Client: mcp, so the backend
                // runs the SQLResultsFormatter and returns formatted_results as a string.
                const insight = await createTestInsight(generateUniqueKey('HogQL Optimized Shape'))

                const result = await queryTool.handler(context, {
                    insightId: String(insight.id),
                    output_format: 'optimized',
                })
                const response = parseToolResponse(result)

                expect(response).toHaveProperty('results')
                expect(typeof response.results).toBe('string')
            })

            it('TrendsQuery with output_format=json returns an array of series', async () => {
                const insight = await createTestTrendsInsight(generateUniqueKey('Trends JSON Shape'))

                const result = await queryTool.handler(context, {
                    insightId: String(insight.id),
                    output_format: 'json',
                })
                const response = parseToolResponse(result)

                expect(response).toHaveProperty('results')
                expect(Array.isArray(response.results)).toBe(true)
            })

            it('TrendsQuery with output_format=optimized returns a formatted string', async () => {
                // The API client always sends X-PostHog-Client: mcp, so the backend
                // runs the TrendsResultsFormatter and returns formatted_results as a string.
                const insight = await createTestTrendsInsight(generateUniqueKey('Trends Optimized Shape'))

                const result = await queryTool.handler(context, {
                    insightId: String(insight.id),
                    output_format: 'optimized',
                })
                const response = parseToolResponse(result)

                expect(response).toHaveProperty('results')
                expect(typeof response.results).toBe('string')
            })
        })
    })

    describe('insight CRUD id handling', () => {
        it('insight-get accepts a numeric id', async () => {
            const insight = await createTestInsight(generateUniqueKey('Get By Numeric Id'))

            const parsed = insightGetTool.schema.parse({ id: insight.id })
            const result = (await insightGetTool.handler(context, parsed)) as { id: number; short_id: string }

            expect(result.id).toBe(insight.id)
            expect(result.short_id).toBe(insight.short_id)
        })

        it('insight-get accepts a short_id', async () => {
            const insight = await createTestInsight(generateUniqueKey('Get By Short Id'))

            // Document current behavior: the generated schema types `id` as number only,
            // but the PostHog API accepts both numeric id and short_id on the retrieve path.
            // If this test ever fails, we need to widen the schema to z.union([z.number(), z.string()]).
            const parsed = insightGetTool.schema.parse({ id: insight.short_id as unknown as number })
            const result = (await insightGetTool.handler(context, parsed)) as { id: number; short_id: string }

            expect(result.short_id).toBe(insight.short_id)
        })

        it('insight-update updates by numeric id and returns the updated insight', async () => {
            const insight = await createTestInsight(generateUniqueKey('Update By Numeric Id'))
            const newName = generateUniqueKey('Renamed')

            const parsed = insightUpdateTool.schema.parse({ id: insight.id, name: newName })
            const result = (await insightUpdateTool.handler(context, parsed)) as { id: number; name: string }

            expect(result.id).toBe(insight.id)
            expect(result.name).toBe(newName)
        })

        it('insight-create returns numeric id + short_id for later lookup', async () => {
            const name = generateUniqueKey('Create And Look Up')
            const parsed = insightCreateTool.schema.parse({
                name,
                query: SAMPLE_HOGQL_QUERIES.pageviews,
            })
            const created = (await insightCreateTool.handler(context, parsed)) as {
                id: number
                short_id: string
                name: string
            }
            createdResources.insights.push(created.id)

            expect(created.id).toEqual(expect.any(Number))
            expect(created.short_id).toEqual(expect.any(String))
            expect(created.name).toBe(name)

            // Round-trip: the numeric id returned from create should work with insight-get
            const fetched = (await insightGetTool.handler(
                context,
                insightGetTool.schema.parse({ id: created.id })
            )) as { id: number }
            expect(fetched.id).toBe(created.id)
        })

        it('insight-delete soft-deletes by numeric id', async () => {
            const insight = await createTestInsight(generateUniqueKey('Delete By Numeric Id'))

            const parsed = insightDeleteTool.schema.parse({ id: insight.id })
            const result = (await insightDeleteTool.handler(context, parsed)) as {
                id: number
                deleted: boolean
            }

            expect(result.id).toBe(insight.id)
            expect(result.deleted).toBe(true)

            // Drop from cleanup since we already deleted it
            createdResources.insights = createdResources.insights.filter((id) => id !== insight.id)
        })
    })
})
