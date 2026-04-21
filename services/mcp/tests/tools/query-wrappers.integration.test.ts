import { beforeAll, describe, expect, it } from 'vitest'

import type { ApiClient } from '@/api/client'
import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'
import { POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, type Context } from '@/tools/types'

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
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result._posthogUrl).toMatch(/\/insights\/new#q=/)

            // Formatted results should contain pipe-separated values (the formatter output)
            expect(typeof result.results).toBe('object')
            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
        })

        it('should include pipe-separated table in formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
                interval: 'day',
            })) as any

            // Formatted results should contain pipe-separated values (the formatter output)
            expect(typeof result.results).toBe('object')
            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
            expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('|')
        })

        it('should execute trends with breakdown', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
                breakdownFilter: {
                    breakdowns: [{ property: '$browser', type: 'event' }],
                },
            })) as any

            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
        })
    })

    describe('query-funnel', () => {
        it('should execute a basic funnel query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-funnel')
            const result = (await tool.handler(context, {
                series: [
                    { kind: 'EventsNode', event: '$pageview' },
                    { kind: 'EventsNode', event: '$pageleave' },
                ],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')

            // Formatted results should contain pipe-separated values (the formatter output)
            expect(typeof result.results).toBe('object')
            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
            expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('|')
        })
    })

    describe('query-retention', () => {
        it('should execute a basic retention query', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-retention')
            const result = (await tool.handler(context, {
                retentionFilter: {
                    targetEntity: { id: '$pageview', type: 'events' },
                    returningEntity: { id: '$pageview', type: 'events' },
                    period: 'Day',
                    totalIntervals: 7,
                },
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('_posthogUrl')
            expect(typeof result.results).toBe('object')
        })
    })

    describe('query-stickiness', () => {
        it('should execute a basic stickiness query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-stickiness')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')

            // Formatted results should contain pipe-separated values (the formatter output)
            expect(typeof result.results).toBe('object')
            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
            expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('|')
        })

        it('should generate a valid PostHog URL with StickinessQuery kind', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-stickiness')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result._posthogUrl).toContain('/insights/new#q=')
            const hash = result._posthogUrl.split('#q=')[1]
            expect(hash).toBeTruthy()
            const parsed = JSON.parse(decodeURIComponent(hash))
            expect(parsed.kind).toBe('InsightVizNode')
            expect(parsed.source.kind).toBe('StickinessQuery')
        })
    })

    describe('query-paths', () => {
        it('should execute a basic paths query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-paths')
            const result = (await tool.handler(context, {
                pathsFilter: {
                    includeEventTypes: ['$pageview'],
                    stepLimit: 5,
                },
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
            expect(result._posthogUrl).toMatch(/\/insights\/new#q=/)

            // Formatted results should contain pipe-separated values (the formatter output)
            expect(typeof result.results).toBe('object')
            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
            expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toContain('|')
        })

        it('should execute a paths query with start point', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-paths')
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
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-30d' },
                interval: 'day',
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
        })

        it('should execute lifecycle with toggled lifecycles filter', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle')
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
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-90d' },
                interval: 'week',
            })) as any

            expect(result).toHaveProperty('results')
        })
    })

    describe('query-llm-traces-list', () => {
        it('should execute a traces query and return formatted results', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-llm-traces-list')
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
        it('should wrap query in InsightVizNode in the URL', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends')
            const result = (await tool.handler(context, {
                series: [{ kind: 'EventsNode', event: '$pageview' }],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result._posthogUrl).toContain('/insights/new#q=')
            const hash = result._posthogUrl.split('#q=')[1]
            expect(hash).toBeTruthy()
            const parsed = JSON.parse(decodeURIComponent(hash))
            expect(parsed.kind).toBe('InsightVizNode')
            expect(parsed.source.kind).toBe('TrendsQuery')
        })
    })

    describe('query-trends-actors', () => {
        const trendsSource = {
            kind: 'TrendsQuery',
            series: [{ kind: 'EventsNode', event: '$pageview', math: 'total' }],
            dateRange: { date_from: '-30d' },
            interval: 'day',
        }

        it('rejects when day is missing', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends-actors')
            await expect(tool.handler(context, { source: trendsSource })).rejects.toThrow()
        })

        it('returns a flat {columns, rows} table with the actors projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends-actors')
            const result = (await tool.handler(context, {
                source: trendsSource,
                day: '2026-03-25',
            })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('hasMore')
            expect(result).toHaveProperty('offset')
            expect(result).toHaveProperty('results')
            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it.each([
            [true, ['distinct_id', 'email', 'name', 'event_count', 'recordings']],
            [false, ['distinct_id', 'email', 'name', 'event_count']],
        ] as const)(
            'returns expected columns when includeRecordings=%s',
            async (includeRecordings, expectedColumns) => {
                const tool = getToolByName(GENERATED_TOOLS, 'query-trends-actors')
                const result = (await tool.handler(context, {
                    source: trendsSource,
                    day: '2026-03-25',
                    includeRecordings,
                })) as any

                expect(result.results.columns).toEqual(expectedColumns)
            }
        )

        it('filters actors by day and series selectors', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends-actors')
            const result = (await tool.handler(context, {
                source: trendsSource,
                day: '2026-03-25',
                series: 0,
            })) as any

            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it('accepts breakdown as an array of values', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends-actors')
            const sourceWithBreakdown = {
                ...trendsSource,
                breakdownFilter: {
                    breakdowns: [{ property: '$browser', type: 'event' }],
                },
            }
            const result = (await tool.handler(context, {
                source: sourceWithBreakdown,
                day: '2026-03-25',
                breakdown: ['Chrome'],
            })) as any

            expect(Array.isArray(result.results.results)).toBe(true)
        })
    })
})
