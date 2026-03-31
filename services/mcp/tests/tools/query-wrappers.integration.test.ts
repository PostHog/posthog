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

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
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

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
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

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
        })
    })

    describe('query-stickiness', () => {
        it('should execute a basic stickiness query and return formatted results', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-stickiness'
            )
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
        })

        it('should generate a valid PostHog URL with StickinessQuery kind', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-stickiness'
            )
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result._posthogUrl).toContain('/insights/new?q=')
            const url = new URL(result._posthogUrl)
            const queryParam = url.searchParams.get('q')
            expect(queryParam).toBeTruthy()
            const parsed = JSON.parse(decodeURIComponent(queryParam!))
            expect(parsed.kind).toBe('StickinessQuery')
        })
    })

    describe('query-paths', () => {
        it('should execute a basic paths query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-paths')
            const result = (await tool.handler(context, {
                pathsFilter: {
                    includeEventTypes: ['$pageview'],
                    stepLimit: 5,
                },
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result._posthogUrl).toMatch(/\/insights\/new\?q=/)
        })

        it('should execute a paths query with start point', async () => {
            const tool = getToolByName(GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>, 'query-paths')
            const result = (await tool.handler(context, {
                pathsFilter: {
                    includeEventTypes: ['$pageview'],
                    startPoint: '/',
                    stepLimit: 5,
                },
                dateRange: { date_from: '-7d' },
                filterTestAccounts: true,
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
        })
    })

    describe('query-lifecycle', () => {
        it('should execute a basic lifecycle query and return formatted results', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-lifecycle'
            )
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-30d' },
                interval: 'day',
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
        })

        it('should execute lifecycle with toggled lifecycles filter', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-lifecycle'
            )
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-30d' },
                interval: 'day',
                lifecycleFilter: {
                    toggledLifecycles: ['new', 'dormant'],
                },
            })) as any

            expect(result).toHaveProperty('results')
        })

        it('should execute lifecycle with weekly interval', async () => {
            const tool = getToolByName(
                GENERATED_TOOLS as Record<string, () => ToolBase<ZodObjectAny>>,
                'query-lifecycle'
            )
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-90d' },
                interval: 'week',
            })) as any

            expect(result).toHaveProperty('results')
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

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            // TracesQuery may not have a formatter — result could be string or JSON fallback
            expect(result.results !== undefined).toBe(true)
        })
    })

    describe('factory behavior', () => {
        it('should generate a valid PostHog URL with kind', async () => {
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
