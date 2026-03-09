import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import logsListAttributesTool from '@/tools/logs/listAttributes'
import logsListAttributeValuesTool from '@/tools/logs/listAttributeValues'
import logsQueryTool from '@/tools/logs/query'
import type { Context } from '@/tools/types'

describe('Logs', { concurrent: false }, () => {
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

    describe('logs-query tool', () => {
        const queryTool = logsQueryTool()

        it('should query logs with date range', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                dateFrom,
                dateTo,
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(logsData).toHaveProperty('hasMore')
            expect(logsData).toHaveProperty('nextCursor')
            expect(Array.isArray(logsData.results)).toBe(true)
        })

        it('should query logs with severity filter', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                dateFrom,
                dateTo,
                severityLevels: ['error', 'warn'],
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
        })

        it('should query logs with limit', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                dateFrom,
                dateTo,
                limit: 10,
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
            expect(logsData.results.length).toBeLessThanOrEqual(10)
        })

        it('should filter logs matching a known value', async () => {
            const dateFrom = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            // Fetch one log to get a real body value to search for
            const seed = await queryTool.handler(context, { dateFrom, dateTo, limit: 1 })
            const seedData = parseToolResponse(seed)

            if (seedData.results.length === 0) {
                // No logs in the test environment for the last 7 days — skip gracefully
                return
            }

            const snippet = seedData.results[0].body.slice(0, 20)

            const result = await queryTool.handler(context, {
                dateFrom,
                dateTo,
                filters: [{ key: 'message', operator: 'icontains', type: 'log', value: snippet }],
            })
            const logsData = parseToolResponse(result)

            expect(logsData.results.length).toBeGreaterThan(0)
            for (const log of logsData.results) {
                expect(log.body.toLowerCase()).toContain(snippet.toLowerCase())
            }
        })

        it('should return empty results for a non-matching filter', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                dateFrom,
                dateTo,
                filters: [
                    {
                        key: 'message',
                        operator: 'exact',
                        type: 'log',
                        value: 'IMPOSSIBLE_f47ac10b-58cc-4372-a567-0e02b2c3d479',
                    },
                ],
            })
            const logsData = parseToolResponse(result)

            expect(logsData.results).toHaveLength(0)
        })

        it('should query logs with ordering', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                dateFrom,
                dateTo,
                orderBy: 'earliest',
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
        })
    })

    describe('logs-list-attributes tool', () => {
        const attributesTool = logsListAttributesTool()

        it('should list log attributes', async () => {
            const result = await attributesTool.handler(context, {})
            const attributesData = parseToolResponse(result)

            expect(attributesData).toHaveProperty('results')
            expect(attributesData).toHaveProperty('count')
            expect(Array.isArray(attributesData.results)).toBe(true)
        })

        it('should list log attributes with search', async () => {
            const result = await attributesTool.handler(context, {
                search: 'service',
            })
            const attributesData = parseToolResponse(result)

            expect(attributesData).toHaveProperty('results')
            expect(Array.isArray(attributesData.results)).toBe(true)
        })

        it('should list resource attributes', async () => {
            const result = await attributesTool.handler(context, {
                attributeType: 'resource',
            })
            const attributesData = parseToolResponse(result)

            expect(attributesData).toHaveProperty('results')
            expect(Array.isArray(attributesData.results)).toBe(true)
        })

        it('should support pagination', async () => {
            const result = await attributesTool.handler(context, {
                limit: 5,
                offset: 0,
            })
            const attributesData = parseToolResponse(result)

            expect(attributesData).toHaveProperty('results')
            expect(attributesData).toHaveProperty('count')
            expect(Array.isArray(attributesData.results)).toBe(true)
            expect(attributesData.results.length).toBeLessThanOrEqual(5)
        })
    })

    describe('logs-list-attribute-values tool', () => {
        const valuesTool = logsListAttributeValuesTool()

        it('should list attribute values for a key', async () => {
            const result = await valuesTool.handler(context, {
                key: 'service.name',
            })
            const valuesData = parseToolResponse(result)

            expect(Array.isArray(valuesData)).toBe(true)
        })

        it('should list attribute values with search', async () => {
            const result = await valuesTool.handler(context, {
                key: 'level',
                search: 'error',
            })
            const valuesData = parseToolResponse(result)

            expect(Array.isArray(valuesData)).toBe(true)
        })

        it('should list resource attribute values', async () => {
            const result = await valuesTool.handler(context, {
                key: 'k8s.container.name',
                attributeType: 'resource',
            })
            const valuesData = parseToolResponse(result)

            expect(Array.isArray(valuesData)).toBe(true)
        })
    })

    describe('Logs workflow', () => {
        it('should support attribute discovery and query workflow', async () => {
            const attributesTool = logsListAttributesTool()
            const queryTool = logsQueryTool()

            const attributesResult = await attributesTool.handler(context, {})
            const attributesData = parseToolResponse(attributesResult)

            expect(attributesData).toHaveProperty('results')
            expect(Array.isArray(attributesData.results)).toBe(true)

            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const queryResult = await queryTool.handler(context, {
                dateFrom,
                dateTo,
                limit: 10,
            })
            const queryData = parseToolResponse(queryResult)

            expect(queryData).toHaveProperty('results')
            expect(Array.isArray(queryData.results)).toBe(true)
        })
    })
})
