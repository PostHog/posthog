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

        it('should execute trends with a GroupNode', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-trends')
            const result = (await tool.handler(context, {
                series: [
                    {
                        kind: 'GroupNode',
                        operator: 'OR',
                        name: 'Pageviews on Safari, Pageleaves on Chrome',
                        math: 'total',
                        nodes: [
                            {
                                kind: 'EventsNode',
                                event: '$pageview',
                                name: 'Pageview',
                                math: 'total',
                                properties: [{ key: '$browser', operator: 'exact', type: 'event', value: ['Safari'] }],
                            },
                            {
                                kind: 'EventsNode',
                                event: '$pageleave',
                                name: 'Pageleave',
                                math: 'total',
                                properties: [{ key: '$browser', operator: 'exact', type: 'event', value: ['Chrome'] }],
                            },
                        ],
                    },
                ],
                dateRange: { date_from: '-7d' },
                interval: 'day',
            })) as any

            expect(result).toHaveProperty('results')
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

        it('should execute a funnel with a GroupNode step using per-node property filters', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-funnel')
            const result = (await tool.handler(context, {
                series: [
                    { kind: 'EventsNode', event: '$pageview' },
                    {
                        kind: 'GroupNode',
                        operator: 'OR',
                        name: 'Pageview on Safari, Pageleave on Chrome',
                        nodes: [
                            {
                                kind: 'EventsNode',
                                event: '$pageview',
                                name: 'Pageview',
                                properties: [{ key: '$browser', operator: 'exact', type: 'event', value: ['Safari'] }],
                            },
                            {
                                kind: 'EventsNode',
                                event: '$pageleave',
                                name: 'Pageleave',
                                properties: [{ key: '$browser', operator: 'exact', type: 'event', value: ['Chrome'] }],
                            },
                        ],
                    },
                ],
                dateRange: { date_from: '-7d' },
            })) as any

            expect(result).toHaveProperty('results')
            expect(result).toHaveProperty('_posthogUrl')
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

            // Paths demo data can have pageviews without a path edge in the selected window.
            expect(typeof result.results).toBe('object')
            expect(typeof result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toBe('string')
            expect(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY]).toMatch(/\||No data recorded for this time period\./)
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

    describe('query-lifecycle-actors', () => {
        const lifecycleSource = {
            kind: 'LifecycleQuery',
            series: [{ kind: 'EventsNode', event: '$pageview' }],
            dateRange: { date_from: '-7d' },
            interval: 'day',
            lifecycleFilter: {},
        }

        it('rejects when day is missing', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle-actors')
            await expect(tool.handler(context, { source: lifecycleSource, status: 'dormant' })).rejects.toThrow()
        })

        it('rejects when status is missing', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle-actors')
            await expect(tool.handler(context, { source: lifecycleSource, day: '2026-03-25' })).rejects.toThrow()
        })

        it('rejects status values outside the lifecycle bucket enum', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle-actors')
            await expect(
                tool.handler(context, { source: lifecycleSource, day: '2026-03-25', status: 'churned' })
            ).rejects.toThrow()
        })

        it('returns a flat {columns, rows} table with the actors projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle-actors')
            const result = (await tool.handler(context, {
                source: lifecycleSource,
                day: '2026-03-25',
                status: 'dormant',
            })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('hasMore')
            expect(result).toHaveProperty('offset')
            expect(result).toHaveProperty('results')
            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it('returns the persons projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle-actors')
            const result = (await tool.handler(context, {
                source: lifecycleSource,
                day: '2026-03-25',
                status: 'new',
            })) as any

            expect(result.results.columns).toEqual(['distinct_id', 'email', 'name'])
        })

        it('wraps the source query in an outer ActorsQuery with select=["actor"] and no orderBy', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-lifecycle-actors')
            const result = (await tool.handler(context, {
                source: lifecycleSource,
                day: '2026-03-25',
                status: 'returning',
            })) as any

            expect(result.query.kind).toBe('ActorsQuery')
            expect(result.query.select).toEqual(['actor'])
            expect(result.query.orderBy).toEqual([])
            expect(result.query.source.kind).toBe('InsightActorsQuery')
            expect(result.query.source.source.kind).toBe('LifecycleQuery')
            expect(result.query.source.status).toBe('returning')
        })
    })

    describe('query-paths-actors', () => {
        const pathsSource = {
            kind: 'PathsQuery',
            pathsFilter: {
                includeEventTypes: ['$pageview'],
                stepLimit: 5,
            },
            dateRange: { date_from: '-7d' },
        }

        it('returns a flat {columns, rows} table with the actors projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-paths-actors')
            const result = (await tool.handler(context, { source: pathsSource })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('hasMore')
            expect(result).toHaveProperty('offset')
            expect(result).toHaveProperty('results')
            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it('wraps the source in an outer ActorsQuery with the event-count projection and ordering', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-paths-actors')
            const result = (await tool.handler(context, {
                source: pathsSource,
                includeRecordings: false,
            })) as any

            expect(result.query.kind).toBe('ActorsQuery')
            expect(result.query.select).toEqual(['actor', 'event_count'])
            expect(result.query.orderBy).toEqual(['event_count DESC', 'actor_id DESC'])
            expect(result.query.source.kind).toBe('InsightActorsQuery')
            expect(result.query.source.source.kind).toBe('PathsQuery')
            expect(result.results.columns).toEqual(['distinct_id', 'email', 'name', 'event_count'])
        })

        it('appends matched_recordings to the projection when includeRecordings is true', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-paths-actors')
            const result = (await tool.handler(context, {
                source: pathsSource,
                includeRecordings: true,
            })) as any

            expect(result.query.select).toEqual(['actor', 'event_count', 'matched_recordings'])
            expect(result.results.columns).toEqual(['distinct_id', 'email', 'name', 'event_count', 'recordings'])
        })

        it('forwards the point-level drilldown keys into source.source.pathsFilter', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-paths-actors')
            const result = (await tool.handler(context, {
                source: {
                    ...pathsSource,
                    pathsFilter: {
                        ...pathsSource.pathsFilter,
                        startPoint: 'https://posthog.com/',
                        endPoint: 'https://us.posthog.com/',
                        pathEndKey: '3_https://us.posthog.com',
                    },
                },
            })) as any

            const sourcePathsFilter = result.query.source.source.pathsFilter
            expect(sourcePathsFilter.pathEndKey).toBe('3_https://us.posthog.com')
            expect(sourcePathsFilter.startPoint).toBe('https://posthog.com/')
            expect(sourcePathsFilter.endPoint).toBe('https://us.posthog.com/')
        })
    })

    describe('query-retention-actors', () => {
        const pageview = { id: '$pageview', name: 'Pageview', type: 'events' }
        const retentionSource = {
            kind: 'RetentionQuery',
            retentionFilter: {
                period: 'Day',
                totalIntervals: 8,
                targetEntity: pageview,
                returningEntity: pageview,
                retentionType: 'retention_first_time',
            },
            dateRange: { date_from: '-30d' },
        }

        it('returns a flat {columns, rows} table with the actors projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-retention-actors')
            const result = (await tool.handler(context, { source: retentionSource, interval: 0 })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('hasMore')
            expect(result).toHaveProperty('offset')
            expect(result).toHaveProperty('results')
            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it('wraps the source in an outer ActorsQuery with the person + per-interval projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-retention-actors')
            const result = (await tool.handler(context, { source: retentionSource, interval: 1 })) as any

            expect(result.query.kind).toBe('ActorsQuery')
            expect(result.query.select).toEqual([
                'person',
                'day_0',
                'day_1',
                'day_2',
                'day_3',
                'day_4',
                'day_5',
                'day_6',
                'day_7',
            ])
            expect(result.query.orderBy).toEqual(['length(appearances) DESC', 'actor_id'])
            expect(result.query.source.kind).toBe('InsightActorsQuery')
            expect(result.query.source.interval).toBe(1)
            expect(result.query.source.source.kind).toBe('RetentionQuery')
            expect(result.results.columns).toEqual([
                'distinct_id',
                'email',
                'name',
                'day_0',
                'day_1',
                'day_2',
                'day_3',
                'day_4',
                'day_5',
                'day_6',
                'day_7',
            ])
        })

        it('derives the interval column count from custom brackets', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-retention-actors')
            const result = (await tool.handler(context, {
                source: {
                    ...retentionSource,
                    retentionFilter: { ...retentionSource.retentionFilter, retentionCustomBrackets: [1, 3, 5] },
                },
                interval: 0,
            })) as any

            // 3 custom brackets → 3 + 1 = 4 interval columns.
            expect(result.query.select).toEqual(['person', 'day_0', 'day_1', 'day_2', 'day_3'])
            expect(result.results.columns).toEqual(['distinct_id', 'email', 'name', 'day_0', 'day_1', 'day_2', 'day_3'])
        })

        it('rejects a totalIntervals above the supported maximum', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-retention-actors')
            await expect(
                tool.handler(context, {
                    source: {
                        ...retentionSource,
                        retentionFilter: { ...retentionSource.retentionFilter, totalIntervals: 50 },
                    },
                    interval: 0,
                })
            ).rejects.toThrow(/maximum is 32/)
        })
    })

    describe('query-stickiness-actors', () => {
        const stickinessSource = {
            kind: 'StickinessQuery',
            series: [{ kind: 'EventsNode', event: '$pageview', name: 'Pageview', math: 'dau' }],
            interval: 'day',
            dateRange: { date_from: '-30d' },
        }

        it('returns a flat {columns, rows} table with the actors projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-stickiness-actors')
            const result = (await tool.handler(context, { source: stickinessSource, day: 1 })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('hasMore')
            expect(result).toHaveProperty('offset')
            expect(result).toHaveProperty('results')
            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it('wraps the source in an outer ActorsQuery with the actor projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-stickiness-actors')
            const result = (await tool.handler(context, { source: stickinessSource, day: 2, series: 0 })) as any

            expect(result.query.kind).toBe('ActorsQuery')
            expect(result.query.select).toEqual(['actor'])
            expect(result.query.orderBy).toEqual([])
            expect(result.query.source.kind).toBe('InsightActorsQuery')
            expect(result.query.source.day).toBe(2)
            expect(result.query.source.series).toBe(0)
            expect(result.query.source.source.kind).toBe('StickinessQuery')
            expect(result.results.columns).toEqual(['distinct_id', 'email', 'name'])
        })

        it('does not project a recordings column (membership-based output)', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-stickiness-actors')
            const result = (await tool.handler(context, { source: stickinessSource, day: 1 })) as any

            expect(result.query.select).not.toContain('matched_recordings')
            expect(result.results.columns).not.toContain('recordings')
        })
    })

    describe('query-funnel-actors', () => {
        const funnelSource = {
            kind: 'FunnelsQuery',
            series: [
                { kind: 'EventsNode', event: '$pageview', name: 'Pageview' },
                { kind: 'EventsNode', event: '$pageview', name: '$pageview' },
            ],
            funnelsFilter: { funnelVizType: 'steps' },
            dateRange: { date_from: '-30d' },
            interval: 'day',
        }

        it('returns a flat {columns, rows} table with the actors projection', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-funnel-actors')
            const result = (await tool.handler(context, { source: funnelSource, funnelStep: 2 })) as any

            expect(result).toHaveProperty('query')
            expect(result).toHaveProperty('hasMore')
            expect(result).toHaveProperty('offset')
            expect(result).toHaveProperty('results')
            expect(Array.isArray(result.results.results)).toBe(true)
        })

        it('wraps the source in an outer ActorsQuery and passes the converted step through', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-funnel-actors')
            const result = (await tool.handler(context, { source: funnelSource, funnelStep: 2 })) as any

            expect(result.query.kind).toBe('ActorsQuery')
            expect(result.query.orderBy).toEqual([])
            expect(result.query.source.kind).toBe('FunnelsActorsQuery')
            expect(result.query.source.funnelStep).toBe(2)
            expect(result.query.source.source.kind).toBe('FunnelsQuery')
            // includeRecordings defaults to true, so the recordings column is projected.
            expect(result.query.select).toEqual(['actor', 'matched_recordings'])
            expect(result.results.columns).toEqual(['distinct_id', 'email', 'name', 'recordings'])
        })

        it('passes a negative funnelStep through for the dropped-off cohort', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-funnel-actors')
            const result = (await tool.handler(context, { source: funnelSource, funnelStep: -2 })) as any

            expect(result.query.source.funnelStep).toBe(-2)
            expect(result.query.source.source.kind).toBe('FunnelsQuery')
        })

        it('omits the recordings column when includeRecordings is false', async () => {
            const tool = getToolByName(GENERATED_TOOLS, 'query-funnel-actors')
            const result = (await tool.handler(context, {
                source: funnelSource,
                funnelStep: 2,
                includeRecordings: false,
            })) as any

            expect(result.query.select).toEqual(['actor'])
            expect(result.query.select).not.toContain('matched_recordings')
            expect(result.results.columns).not.toContain('recordings')
        })
    })
})
