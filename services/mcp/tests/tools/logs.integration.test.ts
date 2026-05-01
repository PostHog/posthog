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
import { GENERATED_TOOLS } from '@/tools/generated/logs'
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

    describe('query-logs tool', () => {
        const queryTool = GENERATED_TOOLS['query-logs']!()

        it('should query logs with date range', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                query: { dateRange: { date_from: dateFrom, date_to: dateTo } },
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
        })

        it('should query logs with severity filter', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    severityLevels: ['error', 'warn'],
                },
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
        })

        it('should query logs with limit', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    limit: 10,
                },
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
            expect(logsData.results.length).toBeLessThanOrEqual(10)
        })

        it('should filter logs matching a known value', async () => {
            const dateFrom = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const seed = await queryTool.handler(context, {
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    limit: 1,
                },
            })
            const seedData = parseToolResponse(seed)

            if (seedData.results.length === 0) {
                return
            }

            const snippet = seedData.results[0].body.slice(0, 20)

            const result = await queryTool.handler(context, {
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    filterGroup: [{ key: 'message', operator: 'icontains', type: 'log', value: snippet }],
                },
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
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    filterGroup: [
                        {
                            key: 'message',
                            operator: 'exact',
                            type: 'log',
                            value: ['IMPOSSIBLE_f47ac10b-58cc-4372-a567-0e02b2c3d479'],
                        },
                    ],
                },
            })
            const logsData = parseToolResponse(result)

            expect(logsData.results).toHaveLength(0)
        })

        it('should query logs with ordering', async () => {
            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const result = await queryTool.handler(context, {
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    orderBy: 'earliest',
                },
            })
            const logsData = parseToolResponse(result)

            expect(logsData).toHaveProperty('results')
            expect(Array.isArray(logsData.results)).toBe(true)
        })
    })

    describe('logs-attributes-list tool', () => {
        const attributesTool = GENERATED_TOOLS['logs-attributes-list']!()

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
                attribute_type: 'resource',
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

    describe('logs-attribute-values-list tool', () => {
        const valuesTool = GENERATED_TOOLS['logs-attribute-values-list']!()

        it('should list attribute values for a key', async () => {
            const result = await valuesTool.handler(context, {
                key: 'service.name',
            })
            const valuesData = parseToolResponse(result)

            expect(valuesData).toHaveProperty('results')
        })

        it('should list attribute values with search', async () => {
            const result = await valuesTool.handler(context, {
                key: 'level',
                value: 'error',
            })
            const valuesData = parseToolResponse(result)

            expect(valuesData).toHaveProperty('results')
        })

        it('should list resource attribute values', async () => {
            const result = await valuesTool.handler(context, {
                key: 'k8s.container.name',
                attribute_type: 'resource',
            })
            const valuesData = parseToolResponse(result)

            expect(valuesData).toHaveProperty('results')
        })
    })

    describe('Logs workflow', () => {
        it('should support attribute discovery and query workflow', async () => {
            const attributesTool = GENERATED_TOOLS['logs-attributes-list']!()
            const queryTool = GENERATED_TOOLS['query-logs']!()

            const attributesResult = await attributesTool.handler(context, {})
            const attributesData = parseToolResponse(attributesResult)

            expect(attributesData).toHaveProperty('results')
            expect(Array.isArray(attributesData.results)).toBe(true)

            const dateFrom = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString()
            const dateTo = new Date().toISOString()

            const queryResult = await queryTool.handler(context, {
                query: {
                    dateRange: { date_from: dateFrom, date_to: dateTo },
                    limit: 10,
                },
            })
            const queryData = parseToolResponse(queryResult)

            expect(queryData).toHaveProperty('results')
            expect(Array.isArray(queryData.results)).toBe(true)
        })
    })
})
