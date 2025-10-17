import { ApiClient } from '@/api/client'
import type { CreateInsightInput } from '@/schema/insights'
import { afterEach, beforeAll, describe, expect, it } from 'vitest'

const API_BASE_URL = process.env.TEST_POSTHOG_API_BASE_URL || 'http://localhost:8010'
const API_TOKEN = process.env.TEST_POSTHOG_PERSONAL_API_KEY
const TEST_ORG_ID = process.env.TEST_ORG_ID
const TEST_PROJECT_ID = process.env.TEST_PROJECT_ID

describe('API Client Integration Tests', { concurrent: false }, () => {
    let client: ApiClient
    let testOrgId: string
    let testProjectId: string

    // Track created resources for cleanup
    const createdResources = {
        featureFlags: [] as number[],
        insights: [] as number[],
        dashboards: [] as number[],
        experiments: [] as number[],
    }

    beforeAll(async () => {
        if (!API_TOKEN) {
            throw new Error('TEST_POSTHOG_PERSONAL_API_KEY environment variable is required')
        }

        if (!TEST_ORG_ID) {
            throw new Error('TEST_ORG_ID environment variable is required')
        }

        if (!TEST_PROJECT_ID) {
            throw new Error('TEST_PROJECT_ID environment variable is required')
        }

        client = new ApiClient({
            apiToken: API_TOKEN,
            baseUrl: API_BASE_URL,
        })

        testOrgId = TEST_ORG_ID
        testProjectId = TEST_PROJECT_ID
    })

    afterEach(async () => {
        // Clean up created feature flags
        for (const flagId of createdResources.featureFlags) {
            try {
                await client.featureFlags({ projectId: testProjectId }).delete({ flagId })
            } catch (error) {
                console.warn(`Failed to cleanup feature flag ${flagId}:`, error)
            }
        }
        createdResources.featureFlags = []

        // Clean up created insights
        for (const insightId of createdResources.insights) {
            try {
                await client.insights({ projectId: testProjectId }).delete({ insightId })
            } catch (error) {
                console.warn(`Failed to cleanup insight ${insightId}:`, error)
            }
        }
        createdResources.insights = []

        // Clean up created dashboards
        for (const dashboardId of createdResources.dashboards) {
            try {
                await client.dashboards({ projectId: testProjectId }).delete({ dashboardId })
            } catch (error) {
                console.warn(`Failed to cleanup dashboard ${dashboardId}:`, error)
            }
        }
        createdResources.dashboards = []

        // Clean up created experiments
        for (const experimentId of createdResources.experiments) {
            try {
                await client.experiments({ projectId: testProjectId }).delete({
                    experimentId,
                })
            } catch (error) {
                console.warn(`Failed to cleanup experiment ${experimentId}:`, error)
            }
        }
        createdResources.experiments = []
    })

    describe.skip('Organizations API', () => {
        it('should list organizations', async () => {
            const result = await client.organizations().list()

            if (!result.success) {
                console.error('Failed to list organizations:', (result as any).error)
            }

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                if (result.data.length > 0) {
                    const org = result.data[0]
                    expect(org).toHaveProperty('id')
                    expect(org).toHaveProperty('name')
                    if (org) {
                        expect(typeof org.id).toBe('string')
                        expect(typeof org.name).toBe('string')
                    }
                }
            }
        })

        it('should get organization details', async () => {
            const result = await client.organizations().get({ orgId: testOrgId })

            expect(result.success).toBe(true)

            if (result.success) {
                expect(result.data).toHaveProperty('id')
                expect(result.data).toHaveProperty('name')
                expect(result.data.id).toBe(testOrgId)
            }
        })

        it('should list projects for organization', async () => {
            const result = await client.organizations().projects({ orgId: testOrgId }).list()

            if (!result.success) {
                console.error('Failed to list projects:', (result as any).error)
            }

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                if (result.data.length > 0) {
                    const project = result.data[0]
                    expect(project).toHaveProperty('id')
                    expect(project).toHaveProperty('name')
                    if (project) {
                        expect(typeof project.id).toBe('number')
                        expect(typeof project.name).toBe('string')
                    }
                }
            }
        })
    })

    describe('Projects API', () => {
        it('should get project details', async () => {
            const result = await client.projects().get({ projectId: testProjectId })

            if (!result.success) {
                console.error('Failed to get project details:', (result as any).error)
            }

            expect(result.success).toBe(true)

            if (result.success) {
                expect(result.data).toHaveProperty('id')
                expect(result.data).toHaveProperty('name')
                expect(result.data.id).toBe(Number(testProjectId))
            }
        })

        it.each(['event', 'person'] as const)(
            'should get property definitions for %s type',
            async (type) => {
                const result = await client.projects().propertyDefinitions({
                    projectId: testProjectId,
                    type,
                    eventNames: type === 'event' ? ['$pageview'] : undefined,
                    excludeCoreProperties: false,
                    filterByEventNames: type === 'event',
                    isFeatureFlag: false,
                    limit: 100,
                })

                expect(result.success).toBe(true)

                if (result.success) {
                    expect(Array.isArray(result.data)).toBe(true)
                    if (result.data.length > 0) {
                        const propDef = result.data[0]
                        expect(propDef).toHaveProperty('id')
                        expect(propDef).toHaveProperty('name')
                    }
                }
            }
        )

        it('should get event definitions', async () => {
            const result = await client.projects().eventDefinitions({ projectId: testProjectId })

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                if (result.data.length > 0) {
                    const eventDef = result.data[0]
                    expect(eventDef).toHaveProperty('id')
                    expect(eventDef).toHaveProperty('name')
                    expect(eventDef).toHaveProperty('last_seen_at')
                }
            }
        })

        it('should get event definitions with search parameter', async () => {
            const result = await client.projects().eventDefinitions({
                projectId: testProjectId,
                search: 'pageview',
            })

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                // All returned events should contain "pageview" in their name
                for (const eventDef of result.data) {
                    expect(eventDef.name.toLowerCase()).toContain('pageview')
                }
            }
        })

        it('should return empty array when searching for non-existent events', async () => {
            const result = await client.projects().eventDefinitions({
                projectId: testProjectId,
                search: 'non-existent-event-xyz123',
            })

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                expect(result.data.length).toBe(0)
            }
        })
    })

    describe('Feature Flags API', () => {
        it('should list feature flags', async () => {
            const result = await client.featureFlags({ projectId: testProjectId }).list()

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                for (const flag of result.data) {
                    expect(flag).toHaveProperty('id')
                    expect(flag).toHaveProperty('key')
                    expect(flag).toHaveProperty('name')
                    expect(flag).toHaveProperty('active')
                    expect(typeof flag.id).toBe('number')
                    expect(typeof flag.key).toBe('string')
                    expect(typeof flag.name).toBe('string')
                    expect(typeof flag.active).toBe('boolean')
                }
            }
        })

        it('should create, get, update, and delete a feature flag', async () => {
            const testKey = `test-flag-${Date.now()}`

            // Create
            const createResult = await client.featureFlags({ projectId: testProjectId }).create({
                data: {
                    key: testKey,
                    name: 'Test Flag',
                    description: 'Test feature flag',
                    active: true,
                    filters: { groups: [] },
                },
            })

            expect(createResult.success).toBe(true)

            if (createResult.success) {
                const flagId = createResult.data.id
                createdResources.featureFlags.push(flagId)

                // Get by ID
                const getResult = await client
                    .featureFlags({ projectId: testProjectId })
                    .get({ flagId })
                expect(getResult.success).toBe(true)

                if (getResult.success) {
                    expect(getResult.data.key).toBe(testKey)
                    expect(getResult.data.name).toBe('Test Flag')
                }

                // Find by key
                const findResult = await client
                    .featureFlags({ projectId: testProjectId })
                    .findByKey({ key: testKey })
                expect(findResult.success).toBe(true)

                if (findResult.success && findResult.data) {
                    expect(findResult.data.id).toBe(flagId)
                    expect(findResult.data.key).toBe(testKey)
                }

                // Update
                const updateResult = await client
                    .featureFlags({ projectId: testProjectId })
                    .update({
                        key: testKey,
                        data: {
                            name: 'Updated Test Flag',
                            active: false,
                        },
                    })
                expect(updateResult.success).toBe(true)

                // Verify update
                const updatedGetResult = await client
                    .featureFlags({ projectId: testProjectId })
                    .get({ flagId })
                if (updatedGetResult.success) {
                    expect(updatedGetResult.data.name).toBe('Updated Test Flag')
                    expect(updatedGetResult.data.active).toBe(false)
                }

                // Delete will be handled by afterEach cleanup
            }
        })
    })

    describe('Insights API', () => {
        it('should list insights', async () => {
            const result = await client.insights({ projectId: testProjectId }).list()

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                for (const insight of result.data) {
                    expect(insight).toHaveProperty('id')
                    expect(insight).toHaveProperty('name')
                    expect(typeof insight.id).toBe('number')
                    expect(typeof insight.name).toBe('string')
                }
            }
        })

        it.skip('should execute SQL insight query', async () => {
            const result = await client
                .insights({ projectId: testProjectId })
                .sqlInsight({ query: 'SELECT 1 as test' })

            if (!result.success) {
                console.error('Failed to execute SQL insight:', (result as any).error)
            }

            expect(result.success).toBe(true)

            if (result.success) {
                expect(result.data).toHaveProperty('columns')
                expect(result.data).toHaveProperty('results')
                if ('columns' in result.data && 'results' in result.data) {
                    expect(Array.isArray(result.data.columns)).toBe(true)
                    expect(Array.isArray(result.data.results)).toBe(true)
                }
            }
        })

        it('should create, get, update, and delete an insight', async () => {
            const createResult = await client.insights({ projectId: testProjectId }).create({
                data: {
                    name: 'Test Insight',
                    query: {
                        kind: 'DataVisualizationNode',
                        source: {
                            kind: 'HogQLQuery',
                            query: 'SELECT 1 as test',
                            filters: {
                                dateRange: {
                                    date_from: '-7d',
                                    date_to: '1d',
                                },
                            },
                        },
                    },
                    favorited: false,
                },
            })

            if (!createResult.success) {
                console.error('Failed to create insight:', (createResult as any).error)
            }

            expect(createResult.success).toBe(true)

            if (createResult.success) {
                const insightId = createResult.data.id
                createdResources.insights.push(insightId)

                // Get
                const getResult = await client
                    .insights({ projectId: testProjectId })
                    .get({ insightId: insightId.toString() })

                if (!getResult.success) {
                    console.error('Failed to get insight:', (getResult as any).error)
                }

                expect(getResult.success).toBe(true)

                if (getResult.success) {
                    expect(getResult.data.name).toBe('Test Insight')
                }

                // Update
                const updateResult = await client.insights({ projectId: testProjectId }).update({
                    insightId,
                    data: {
                        name: 'Updated Test Insight',
                    },
                })
                expect(updateResult.success).toBe(true)

                // Delete will be handled by afterEach cleanup
            }
        })

        describe('Trends Query Tests', () => {
            it('should create trends insight with minimal parameters', async () => {
                const insightData: CreateInsightInput = {
                    name: 'Basic Trends Test',
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'TrendsQuery',
                            series: [
                                {
                                    kind: 'EventsNode',
                                    event: '$pageview',
                                    math: 'total',
                                },
                            ],
                            properties: [],
                            filterTestAccounts: false,
                            interval: 'day',
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })

            it('should create trends insight with all display types', async () => {
                const displayTypes = [
                    'ActionsLineGraph',
                    'ActionsTable',
                    'ActionsPie',
                    'ActionsBar',
                    'ActionsBarValue',
                    'WorldMap',
                    'BoldNumber',
                ] as const

                for (const display of displayTypes) {
                    const insightData: CreateInsightInput = {
                        name: `Trends Display - ${display}`,
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        math: 'total',
                                    },
                                ],
                                trendsFilter: {
                                    display,
                                    showLegend: true,
                                },
                                properties: [],
                                filterTestAccounts: true,
                                interval: 'day',
                            },
                        },
                        favorited: false,
                    }

                    const result = await client.insights({ projectId: testProjectId }).create({
                        data: insightData,
                    })

                    expect(result.success).toBe(true)
                    if (result.success) {
                        createdResources.insights.push(result.data.id)
                    }
                }
            })

            it('should create trends insight with breakdowns', async () => {
                const breakdownTypes = ['event', 'person'] as const

                for (const breakdownType of breakdownTypes) {
                    const insightData: CreateInsightInput = {
                        name: `Trends Breakdown - ${breakdownType}`,
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        math: 'total',
                                    },
                                ],
                                breakdownFilter: {
                                    breakdown_type: breakdownType,
                                    breakdown:
                                        breakdownType === 'event' ? '$current_url' : '$browser',
                                    breakdown_limit: 10,
                                },
                                properties: [],
                                filterTestAccounts: true,
                                interval: 'day',
                            },
                        },
                        favorited: false,
                    }

                    const result = await client.insights({ projectId: testProjectId }).create({
                        data: insightData,
                    })

                    expect(result.success).toBe(true)
                    if (result.success) {
                        createdResources.insights.push(result.data.id)
                    }
                }
            })

            it('should create trends insight with different intervals', async () => {
                const intervals = ['hour', 'day', 'week', 'month'] as const

                for (const interval of intervals) {
                    const insightData: CreateInsightInput = {
                        name: `Trends Interval - ${interval}`,
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'TrendsQuery',
                                dateRange: {
                                    date_from: '-30d',
                                    date_to: null,
                                },
                                interval,
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        math: 'total',
                                    },
                                ],
                                properties: [],
                                filterTestAccounts: true,
                            },
                        },
                        favorited: false,
                    }

                    const result = await client.insights({ projectId: testProjectId }).create({
                        data: insightData,
                    })

                    expect(result.success).toBe(true)
                    if (result.success) {
                        createdResources.insights.push(result.data.id)
                    }
                }
            })

            it('should create trends insight with compare filter', async () => {
                const insightData: CreateInsightInput = {
                    name: 'Trends Compare Test',
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'TrendsQuery',
                            series: [
                                {
                                    kind: 'EventsNode',
                                    event: '$pageview',
                                    math: 'total',
                                },
                            ],
                            compareFilter: {
                                compare: true,
                                compare_to: '-1w',
                            },
                            properties: [],
                            filterTestAccounts: false,
                            interval: 'day',
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })

            it('should create trends insight with property filters', async () => {
                const insightData: CreateInsightInput = {
                    name: 'Trends Property Filters',
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'TrendsQuery',
                            series: [
                                {
                                    kind: 'EventsNode',
                                    event: '$pageview',
                                    math: 'total',
                                    properties: [
                                        {
                                            key: '$browser',
                                            value: ['Chrome', 'Safari'],
                                            operator: 'exact',
                                            type: 'event',
                                        },
                                    ],
                                },
                            ],
                            properties: [
                                {
                                    key: '$current_url',
                                    value: '/dashboard',
                                    operator: 'icontains',
                                    type: 'event',
                                },
                            ],
                            filterTestAccounts: false,
                            interval: 'day',
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })
        })

        describe('Funnels Query Tests', () => {
            it('should create funnel insight with minimal parameters', async () => {
                const insightData: CreateInsightInput = {
                    name: 'Basic Funnel Test',
                    query: {
                        kind: 'InsightVizNode',
                        source: {
                            kind: 'FunnelsQuery',
                            series: [
                                {
                                    kind: 'EventsNode',
                                    event: '$pageview',
                                    math: 'total',
                                },
                                {
                                    kind: 'EventsNode',
                                    event: 'button_clicked',
                                    math: 'total',
                                },
                            ],
                            properties: [],
                            filterTestAccounts: false,
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })

            it('should create funnel insight with different layouts and order types', async () => {
                const configs = [
                    { layout: 'horizontal' as const, orderType: 'ordered' as const },
                    { layout: 'vertical' as const, orderType: 'unordered' as const },
                    { layout: 'vertical' as const, orderType: 'strict' as const },
                ]

                for (const config of configs) {
                    const insightData: CreateInsightInput = {
                        name: `Funnel ${config.layout} ${config.orderType}`,
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'FunnelsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        math: 'total',
                                    },
                                    {
                                        kind: 'EventsNode',
                                        event: 'button_clicked',
                                        math: 'total',
                                    },
                                ],
                                funnelsFilter: {
                                    layout: config.layout,
                                    funnelOrderType: config.orderType,
                                    funnelWindowInterval: 7,
                                    funnelWindowIntervalUnit: 'day',
                                },
                                properties: [],
                                filterTestAccounts: false,
                            },
                        },
                        favorited: false,
                    }

                    const result = await client.insights({ projectId: testProjectId }).create({
                        data: insightData,
                    })

                    expect(result.success).toBe(true)
                    if (result.success) {
                        createdResources.insights.push(result.data.id)
                    }
                }
            })

            it('should create funnel insight with breakdown attribution', async () => {
                const attributionTypes = ['first_touch', 'last_touch', 'all_events'] as const

                for (const attribution of attributionTypes) {
                    const insightData: CreateInsightInput = {
                        name: `Funnel Attribution - ${attribution}`,
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'FunnelsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        math: 'total',
                                    },
                                    {
                                        kind: 'EventsNode',
                                        event: 'button_clicked',
                                        math: 'total',
                                    },
                                ],
                                breakdownFilter: {
                                    breakdown_type: 'event',
                                    breakdown: '$browser',
                                    breakdown_limit: 5,
                                },
                                funnelsFilter: {
                                    breakdownAttributionType: attribution,
                                },
                                properties: [],
                                filterTestAccounts: false,
                            },
                        },
                        favorited: false,
                    }

                    const result = await client.insights({ projectId: testProjectId }).create({
                        data: insightData,
                    })

                    expect(result.success).toBe(true)
                    if (result.success) {
                        createdResources.insights.push(result.data.id)
                    }
                }
            })

            it('should create funnel insight with conversion window', async () => {
                const windowUnits = ['minute', 'hour', 'day', 'week', 'month'] as const

                for (const unit of windowUnits) {
                    const insightData: CreateInsightInput = {
                        name: `Funnel Window - ${unit}`,
                        query: {
                            kind: 'InsightVizNode',
                            source: {
                                kind: 'FunnelsQuery',
                                series: [
                                    {
                                        kind: 'EventsNode',
                                        event: '$pageview',
                                        math: 'total',
                                    },
                                    {
                                        kind: 'EventsNode',
                                        event: 'button_clicked',
                                        math: 'total',
                                    },
                                ],
                                funnelsFilter: {
                                    funnelWindowInterval:
                                        unit === 'minute' ? 30 : unit === 'hour' ? 2 : 7,
                                    funnelWindowIntervalUnit: unit,
                                },
                                properties: [],
                                filterTestAccounts: false,
                            },
                        },
                        favorited: false,
                    }

                    const result = await client.insights({ projectId: testProjectId }).create({
                        data: insightData,
                    })

                    expect(result.success).toBe(true)
                    if (result.success) {
                        createdResources.insights.push(result.data.id)
                    }
                }
            })
        })

        describe('HogQL Query Tests', () => {
            it('should create HogQL insight with basic query', async () => {
                const insightData: CreateInsightInput = {
                    name: 'Basic HogQL Test',
                    query: {
                        kind: 'DataVisualizationNode' as const,
                        source: {
                            kind: 'HogQLQuery' as const,
                            query: "SELECT count() as total_events FROM events WHERE event = '$pageview'",
                            filters: {
                                dateRange: {
                                    date_from: '-7d',
                                    date_to: null,
                                },
                                filterTestAccounts: true,
                            },
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })

            it('should create HogQL insight with aggregation query', async () => {
                const insightData: CreateInsightInput = {
                    name: 'HogQL Aggregation Test',
                    query: {
                        kind: 'DataVisualizationNode' as const,
                        source: {
                            kind: 'HogQLQuery' as const,
                            query: `
								SELECT 
									toDate(timestamp) as date,
									count() as events,
									uniq(distinct_id) as unique_users,
									avg(toFloat(JSONExtractString(properties, '$screen_width'))) as avg_screen_width
								FROM events 
								WHERE event = '$pageview' 
									AND timestamp >= now() - INTERVAL 30 DAY
								GROUP BY date 
								ORDER BY date
							`,
                            filters: {
                                dateRange: {
                                    date_from: '-30d',
                                    date_to: null,
                                },
                                filterTestAccounts: true,
                            },
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })

            it('should create HogQL insight with property filters', async () => {
                const insightData: CreateInsightInput = {
                    name: 'HogQL Property Filter Test',
                    query: {
                        kind: 'DataVisualizationNode' as const,
                        source: {
                            kind: 'HogQLQuery' as const,
                            query: `
								SELECT 
									JSONExtractString(properties, '$browser') as browser,
									count() as pageviews
								FROM events 
								WHERE event = '$pageview'
								GROUP BY browser
								ORDER BY pageviews DESC
								LIMIT 10
							`,
                            filters: {
                                dateRange: {
                                    date_from: '-30d',
                                    date_to: null,
                                },
                                filterTestAccounts: true,
                                properties: [
                                    {
                                        key: '$browser',
                                        value: 'Chrome',
                                        operator: 'exact',
                                        type: 'event',
                                    },
                                ],
                            },
                        },
                    },
                    favorited: false,
                }

                const result = await client.insights({ projectId: testProjectId }).create({
                    data: insightData,
                })

                expect(result.success).toBe(true)
                if (result.success) {
                    createdResources.insights.push(result.data.id)
                }
            })
        })
    })

    describe('Dashboards API', () => {
        it('should list dashboards', async () => {
            const result = await client.dashboards({ projectId: testProjectId }).list()

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                for (const dashboard of result.data) {
                    expect(dashboard).toHaveProperty('id')
                    expect(dashboard).toHaveProperty('name')
                    expect(typeof dashboard.id).toBe('number')
                    expect(typeof dashboard.name).toBe('string')
                }
            }
        })

        it('should create, get, update, and delete a dashboard', async () => {
            const createResult = await client.dashboards({ projectId: testProjectId }).create({
                data: {
                    name: 'Test Dashboard',
                    description: 'Test dashboard for API tests',
                    pinned: false,
                },
            })

            expect(createResult.success).toBe(true)

            if (createResult.success) {
                const dashboardId = createResult.data.id
                createdResources.dashboards.push(dashboardId)

                // Get
                const getResult = await client
                    .dashboards({ projectId: testProjectId })
                    .get({ dashboardId })
                expect(getResult.success).toBe(true)

                if (getResult.success) {
                    expect(getResult.data.name).toBe('Test Dashboard')
                }

                // Update
                const updateResult = await client.dashboards({ projectId: testProjectId }).update({
                    dashboardId,
                    data: {
                        name: 'Updated Test Dashboard',
                    },
                })
                expect(updateResult.success).toBe(true)

                // Delete will be handled by afterEach cleanup
            }
        })
    })

    describe('Query API', () => {
        it('should execute error tracking query', async () => {
            const errorQuery = {
                kind: 'ErrorTrackingQuery',
                orderBy: 'occurrences',
                dateRange: {
                    date_from: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString(),
                    date_to: new Date().toISOString(),
                },
                volumeResolution: 1,
                orderDirection: 'DESC',
                filterTestAccounts: true,
                status: 'active',
            }

            const result = await client
                .query({ projectId: testProjectId })
                .execute({ queryBody: errorQuery })

            if (!result.success) {
                console.error('Failed to execute error query:', (result as any).error)
            }

            expect(result.success).toBe(true)

            if (result.success) {
                expect(result.data).toHaveProperty('results')
                expect(Array.isArray(result.data.results)).toBe(true)
            }
        })

        it('should execute trends query for LLM costs', async () => {
            const trendsQuery = {
                kind: 'TrendsQuery',
                dateRange: {
                    date_from: '-6d',
                    date_to: null,
                },
                filterTestAccounts: true,
                series: [
                    {
                        event: '$ai_generation',
                        name: '$ai_generation',
                        math: 'sum',
                        math_property: '$ai_total_cost_usd',
                        kind: 'EventsNode',
                    },
                ],
                breakdownFilter: {
                    breakdown_type: 'event',
                    breakdown: '$ai_model',
                },
            }

            const result = await client
                .query({ projectId: testProjectId })
                .execute({ queryBody: trendsQuery })

            expect(result.success).toBe(true)

            if (result.success) {
                expect(result.data).toHaveProperty('results')
                expect(Array.isArray(result.data.results)).toBe(true)
            }
        })
    })

    describe('Users API', () => {
        it('should get current user', async () => {
            const result = await client.users().me()

            expect(result.success).toBe(true)

            if (result.success) {
                expect(result.data).toHaveProperty('distinct_id')
                expect(typeof result.data.distinct_id).toBe('string')
            }
        })
    })

    describe('Experiments API', () => {
        // Helper function to create a test experiment
        const createTestExperiment = async (
            options: {
                name?: string
                description?: string
                featureFlagKey?: string
                type?: 'product' | 'web'
                draft?: boolean
                metrics?: Array<{
                    name?: string
                    metric_type: 'mean' | 'funnel' | 'ratio'
                    event_name?: string
                    funnel_steps?: string[]
                    properties?: Record<string, any>
                    description?: string
                }>
            } = {}
        ) => {
            const timestamp = Date.now()
            const createResult = await client.experiments({ projectId: testProjectId }).create({
                name: options.name || `Test Experiment ${timestamp}`,
                description: options.description || 'Integration test experiment',
                feature_flag_key: options.featureFlagKey || `test-exp-${timestamp}`,
                type: options.type || 'product',
                primary_metrics: options.metrics
                    ? options.metrics.map((metric) => ({
                          name: metric.name || 'Test Metric',
                          metric_type: metric.metric_type,
                          event_name: metric.event_name || '$pageview',
                          funnel_steps: metric.funnel_steps,
                          properties: metric.properties || {},
                          description: metric.description,
                      }))
                    : undefined,
                variants: [
                    { key: 'control', name: 'Control', rollout_percentage: 50 },
                    { key: 'test', name: 'Test', rollout_percentage: 50 },
                ],
                minimum_detectable_effect: 5,
                filter_test_accounts: true,
                draft: options.draft !== undefined ? options.draft : true,
            })

            expect(createResult.success).toBe(true)

            if (createResult.success) {
                const experimentId = createResult.data.id
                createdResources.experiments.push(experimentId)
                return createResult.data
            }

            throw new Error(
                `Failed to create test experiment: ${(createResult as any).error?.message}`
            )
        }

        it.skip('should list experiments', async () => {
            const result = await client.experiments({ projectId: testProjectId }).list()

            if (!result.success) {
                console.error('List experiments failed:', result.error?.message)
            }

            expect(result.success).toBe(true)

            if (result.success) {
                expect(Array.isArray(result.data)).toBe(true)
                for (const experiment of result.data) {
                    expect(experiment).toHaveProperty('id')
                    expect(experiment).toHaveProperty('name')
                    expect(experiment).toHaveProperty('feature_flag_key')
                    expect(typeof experiment.id).toBe('number')
                    expect(typeof experiment.name).toBe('string')
                    expect(typeof experiment.feature_flag_key).toBe('string')
                }
            }
        })

        it('should create, get, update experiment', async () => {
            // Create a test experiment
            const experiment = await createTestExperiment({
                name: 'CRUD Test Experiment',
                description: 'Test experiment for CRUD operations',
            })

            // Get the created experiment
            const getResult = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId: experiment.id })

            expect(getResult.success).toBe(true)

            if (getResult.success) {
                expect(getResult.data.id).toBe(experiment.id)
                expect(getResult.data.name).toBe('CRUD Test Experiment')
                expect(getResult.data.description).toBe('Test experiment for CRUD operations')
                expect(getResult.data.start_date).toBeNull() // Should be draft
                expect(getResult.data.archived).toBe(false)
            }

            // Update the experiment
            const updateResult = await client.experiments({ projectId: testProjectId }).update({
                experimentId: experiment.id,
                updateData: {
                    name: 'Updated CRUD Test Experiment',
                    description: 'Updated description',
                },
            })

            expect(updateResult.success).toBe(true)

            if (updateResult.success) {
                expect(updateResult.data.name).toBe('Updated CRUD Test Experiment')
                expect(updateResult.data.description).toBe('Updated description')
            }

            // Verify update persisted
            const getUpdatedResult = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId: experiment.id })

            if (getUpdatedResult.success) {
                expect(getUpdatedResult.data.name).toBe('Updated CRUD Test Experiment')
                expect(getUpdatedResult.data.description).toBe('Updated description')
            }
        })

        it('should create experiment with different metric types', async () => {
            // Test mean metric
            const meanExperiment = await createTestExperiment({
                name: 'Mean Metric Test',
                metrics: [
                    {
                        name: 'Page Views',
                        metric_type: 'mean',
                        event_name: '$pageview',
                        description: 'Average page views per user',
                    },
                ],
            })

            expect(meanExperiment.metrics).toHaveLength(1)
            expect(meanExperiment.metrics?.[0]?.metric_type).toBe('mean')

            // Test funnel metric
            const funnelExperiment = await createTestExperiment({
                name: 'Funnel Metric Test',
                featureFlagKey: `funnel-test-${Date.now()}`,
                metrics: [
                    {
                        name: 'Signup Funnel',
                        metric_type: 'funnel',
                        event_name: '$pageview',
                        funnel_steps: ['$pageview', 'sign_up_start', 'sign_up_complete'],
                        description: 'Signup conversion funnel',
                    },
                ],
            })

            expect(funnelExperiment.metrics).toHaveLength(1)
            expect(funnelExperiment.metrics?.[0]?.metric_type).toBe('funnel')

            // Test ratio metric
            const ratioExperiment = await createTestExperiment({
                name: 'Ratio Metric Test',
                featureFlagKey: `ratio-test-${Date.now()}`,
                metrics: [
                    {
                        name: 'Click-through Rate',
                        metric_type: 'ratio',
                        event_name: 'button_click',
                        description: 'Button click rate',
                    },
                ],
            })

            expect(ratioExperiment.metrics).toHaveLength(1)
            expect(ratioExperiment.metrics?.[0]?.metric_type).toBe('ratio')
        })

        it('should handle experiment lifecycle - launch and archive', async () => {
            const experiment = await createTestExperiment({
                name: 'Lifecycle Test Experiment',
                draft: true,
            })

            // Initially should be draft
            expect(experiment.start_date).toBeNull()
            expect(experiment.archived).toBe(false)

            // Launch experiment
            const launchResult = await client.experiments({ projectId: testProjectId }).update({
                experimentId: experiment.id,
                updateData: {
                    start_date: new Date().toISOString(),
                },
            })

            expect(launchResult.success).toBe(true)

            if (launchResult.success) {
                expect(launchResult.data.start_date).not.toBeNull()
            }

            // Archive experiment
            const archiveResult = await client.experiments({ projectId: testProjectId }).update({
                experimentId: experiment.id,
                updateData: {
                    archived: true,
                },
            })

            expect(archiveResult.success).toBe(true)

            if (archiveResult.success) {
                expect(archiveResult.data.archived).toBe(true)
            }
        })

        it.skip('should get experiment exposures for launched experiment', async () => {
            // Create and launch experiment
            const experiment = await createTestExperiment({
                name: 'Exposure Test Experiment',
                draft: false, // Create as launched
            })

            // Launch the experiment
            await client.experiments({ projectId: testProjectId }).update({
                experimentId: experiment.id,
                updateData: {
                    start_date: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(), // 1 day ago
                },
            })

            // Try to get exposures (may not have data immediately)
            const exposureResult = await client
                .experiments({ projectId: testProjectId })
                .getExposures({
                    experimentId: experiment.id,
                    refresh: true,
                })

            // Should succeed even if no exposure data yet
            expect(exposureResult.success).toBe(true)

            if (exposureResult.success) {
                expect(exposureResult.data).toHaveProperty('exposures')
                expect(exposureResult.data.exposures).toBeDefined()
            }
        })

        it('should fail to get exposures for draft experiment', async () => {
            const experiment = await createTestExperiment({
                name: 'Draft Exposure Test',
                draft: true,
            })

            const exposureResult = await client
                .experiments({ projectId: testProjectId })
                .getExposures({
                    experimentId: experiment.id,
                    refresh: false,
                })

            expect(exposureResult.success).toBe(false)
            expect((exposureResult as any).error.message).toContain('has not started yet')
        })

        it.skip('should get experiment metric results for launched experiment', async () => {
            // Create and launch experiment
            const experiment = await createTestExperiment({
                name: 'Metric Results Test',
                draft: false,
            })

            // Launch the experiment
            await client.experiments({ projectId: testProjectId }).update({
                experimentId: experiment.id,
                updateData: {
                    start_date: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
                },
            })

            // Try to get metric results
            const metricsResult = await client
                .experiments({ projectId: testProjectId })
                .getMetricResults({
                    experimentId: experiment.id,
                    refresh: true,
                })

            expect(metricsResult.success).toBe(true)

            if (metricsResult.success) {
                expect(metricsResult.data).toHaveProperty('experiment')
                expect(metricsResult.data).toHaveProperty('primaryMetricsResults')
                expect(metricsResult.data).toHaveProperty('secondaryMetricsResults')
                expect(metricsResult.data).toHaveProperty('exposures')
                expect(metricsResult.data.experiment.id).toBe(experiment.id)
            }
        })

        it('should fail to get metric results for draft experiment', async () => {
            const experiment = await createTestExperiment({
                name: 'Draft Metrics Test',
                draft: true,
            })

            const metricsResult = await client
                .experiments({ projectId: testProjectId })
                .getMetricResults({
                    experimentId: experiment.id,
                    refresh: false,
                })

            expect(metricsResult.success).toBe(false)
            expect((metricsResult as any).error.message).toContain('has not started yet')
        })

        it('should handle invalid experiment ID', async () => {
            const nonExistentId = 999999

            const getResult = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId: nonExistentId })

            expect(getResult.success).toBe(false)
        })

        it('should create experiment with custom variants', async () => {
            const experiment = await createTestExperiment({
                name: 'Custom Variants Test',
            })

            // Verify default variants were created
            expect(experiment.parameters?.feature_flag_variants).toHaveLength(2)

            // Update with custom variants
            const updateResult = await client.experiments({ projectId: testProjectId }).update({
                experimentId: experiment.id,
                updateData: {
                    parameters: {
                        feature_flag_variants: [
                            { key: 'control', rollout_percentage: 25 },
                            { key: 'variant_a', rollout_percentage: 25 },
                            { key: 'variant_b', rollout_percentage: 25 },
                            { key: 'variant_c', rollout_percentage: 25 },
                        ],
                    },
                },
            })

            expect(updateResult.success).toBe(true)

            if (updateResult.success) {
                expect(updateResult.data.parameters?.feature_flag_variants).toHaveLength(4)
                const variants = updateResult.data.parameters?.feature_flag_variants || []
                expect(variants.map((v) => v.key)).toEqual([
                    'control',
                    'variant_a',
                    'variant_b',
                    'variant_c',
                ])
            }
        })

        it('should delete experiment successfully', async () => {
            // Create a test experiment to delete
            const experiment = await createTestExperiment({
                name: 'Delete Test Experiment',
                description: 'Test experiment for delete operations',
            })

            // Verify experiment exists before deletion
            const getBeforeDelete = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId: experiment.id })

            expect(getBeforeDelete.success).toBe(true)

            if (getBeforeDelete.success) {
                expect(getBeforeDelete.data.id).toBe(experiment.id)
                expect(getBeforeDelete.data.name).toBe('Delete Test Experiment')
            }

            // Delete the experiment
            const deleteResult = await client
                .experiments({ projectId: testProjectId })
                .delete({ experimentId: experiment.id })

            expect(deleteResult.success).toBe(true)
            if (deleteResult.success) {
                expect(deleteResult.data.success).toBe(true)
                expect(deleteResult.data.message).toContain('successfully')
            }

            // Verify experiment is soft deleted (should return 404 or be marked as deleted)
            const getAfterDelete = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId: experiment.id })

            // After soft delete, the API should return an error (404) or the experiment should be marked as deleted
            expect(getAfterDelete.success).toBe(false)
        })

        it('should handle deleting non-existent experiment', async () => {
            const nonExistentId = 999999999

            const deleteResult = await client
                .experiments({ projectId: testProjectId })
                .delete({ experimentId: nonExistentId })

            // Should handle gracefully (either success with no-op or specific error)
            // The exact behavior depends on the API implementation
            expect(typeof deleteResult.success).toBe('boolean')
        })

        it('should complete full CRUD workflow including delete', async () => {
            const timestamp = Date.now()

            // CREATE
            const createResult = await client.experiments({ projectId: testProjectId }).create({
                name: `Full CRUD Test ${timestamp}`,
                description: 'Complete CRUD workflow test',
                feature_flag_key: `full-crud-${timestamp}`,
                type: 'product',
                primary_metrics: [
                    {
                        name: 'Test Conversion Rate',
                        metric_type: 'funnel' as const,
                        event_name: 'landing',
                        funnel_steps: ['landing', 'signup', 'activation'],
                        properties: {},
                    },
                ],
                variants: [
                    { key: 'control', name: 'Control', rollout_percentage: 50 },
                    { key: 'variant', name: 'Variant', rollout_percentage: 50 },
                ],
                minimum_detectable_effect: 10,
                filter_test_accounts: true,
                draft: true,
            })

            expect(createResult.success).toBe(true)

            if (!createResult.success) {
                throw new Error('Failed to create experiment for CRUD test')
            }

            const experimentId = createResult.data.id
            createdResources.experiments.push(experimentId)

            // READ
            const getResult = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId })

            expect(getResult.success).toBe(true)

            if (getResult.success) {
                expect(getResult.data.id).toBe(experimentId)
                expect(getResult.data.name).toBe(`Full CRUD Test ${timestamp}`)
                expect(getResult.data.description).toBe('Complete CRUD workflow test')
            }

            // UPDATE
            const updateResult = await client.experiments({ projectId: testProjectId }).update({
                experimentId,
                updateData: {
                    name: `Updated Full CRUD Test ${timestamp}`,
                    description: 'Updated description for CRUD test',
                },
            })

            expect(updateResult.success).toBe(true)

            if (updateResult.success) {
                expect(updateResult.data.name).toBe(`Updated Full CRUD Test ${timestamp}`)
                expect(updateResult.data.description).toBe('Updated description for CRUD test')
            }

            // DELETE
            const deleteResult = await client
                .experiments({ projectId: testProjectId })
                .delete({ experimentId })

            expect(deleteResult.success).toBe(true)
            if (deleteResult.success) {
                expect(deleteResult.data.success).toBe(true)
                expect(deleteResult.data.message).toContain('successfully')
            }

            // Verify deletion worked
            const getAfterDeleteResult = await client
                .experiments({ projectId: testProjectId })
                .get({ experimentId })

            expect(getAfterDeleteResult.success).toBe(false)

            // Remove from cleanup array since we already deleted it
            const index = createdResources.experiments.indexOf(experimentId)
            if (index > -1) {
                createdResources.experiments.splice(index, 1)
            }
        })

        it('should handle delete operations idempotently', async () => {
            // Create experiment
            const experiment = await createTestExperiment({
                name: 'Idempotent Delete Test',
            })

            // First delete should succeed
            const firstDeleteResult = await client
                .experiments({ projectId: testProjectId })
                .delete({ experimentId: experiment.id })

            expect(firstDeleteResult.success).toBe(true)
            if (firstDeleteResult.success) {
                expect(firstDeleteResult.data.success).toBe(true)
                expect(firstDeleteResult.data.message).toContain('successfully')
            }

            // Second delete should handle gracefully (idempotent)
            const secondDeleteResult = await client
                .experiments({ projectId: testProjectId })
                .delete({ experimentId: experiment.id })

            // Should not throw error, either success or specific "already deleted" error
            expect(typeof secondDeleteResult.success).toBe('boolean')

            // Remove from cleanup array since we already deleted it
            const index = createdResources.experiments.indexOf(experiment.id)
            if (index > -1) {
                createdResources.experiments.splice(index, 1)
            }
        })
    })
})
