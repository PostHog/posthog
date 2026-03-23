import { beforeAll, describe, expect, it } from 'vitest'

import type { ApiClient } from '@/api/client'
import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

import {
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    createTestClient,
    createTestContext,
    getToolByName,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '../shared/test-utils'

describe('Query Wrapper Integration Tests', { concurrent: false }, () => {
    let client: ApiClient
    let context: Context

    beforeAll(async () => {
        validateEnvironmentVariables()
        client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    describe('query-trends', () => {
        it('should execute a basic trends query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result.query.kind).toBe('TrendsQuery')
            expect(typeof result.results).toBe('string')
            expect(result._posthogUrl).toMatch(/\/insights\/new\?q=/)
        })

        it('should include pipe-separated table in formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
                interval: 'day',
            })) as any

            // Formatted results should contain pipe-separated values (the formatter output)
            expect(typeof result.results).toBe('string')
            expect(result.results).toContain('|')
        })

        it('should execute trends with breakdown', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
                breakdownFilter: {
                    breakdowns: [{ property: '$browser', type: 'event' }],
                },
            })) as any

            expect(result.query.kind).toBe('TrendsQuery')
            expect(typeof result.results).toBe('string')
        })
    })

    describe('query-funnel', () => {
        it('should execute a basic funnel query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-funnel')
            const result = (await tool.handler(context, {
                series: [
                    { kind: 'EventsNode', event: '$pageview' },
                    { kind: 'EventsNode', event: '$pageleave' },
                ],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result.query.kind).toBe('FunnelsQuery')
            expect(typeof result.results).toBe('string')
        })
    })

    describe('query-retention', () => {
        it('should execute a basic retention query and return formatted results', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-retention'
            )
            const result = (await tool.handler(context, {
                retentionFilter: {
                    targetEntity: { id: '$pageview', type: 'events' },
                    returningEntity: { id: '$pageview', type: 'events' },
                    period: 'Day',
                    totalIntervals: 7,
                },
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result.query.kind).toBe('RetentionQuery')
            expect(typeof result.results).toBe('string')
        })
    })

    describe('query-traces-list', () => {
        it('should execute a traces query and return formatted results', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-traces-list'
            )
            const result = (await tool.handler(context, {
                dateRange: { date_from: '-7d' },
                limit: 10,
            })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result.query.kind).toBe('TracesQuery')
            // TracesQuery may not have a formatter — result could be string or JSON fallback
            expect(result.results !== undefined).toBe(true)
        })
    })

    describe('factory behavior', () => {
        it('should set the kind field automatically', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            // kind should be set by the factory, not passed in params
            expect(result.query.kind).toBe('TrendsQuery')
        })

        it('should generate a valid PostHog URL', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result._posthogUrl).toContain('/insights/new?q=')
            // URL-encoded query should be parseable
            const url = new URL(result._posthogUrl)
            const queryParam = url.searchParams.get('q')
            expect(queryParam).toBeTruthy()
            const parsed = JSON.parse(decodeURIComponent(queryParam!))
            expect(parsed.kind).toBe('TrendsQuery')
        })
    })
})
