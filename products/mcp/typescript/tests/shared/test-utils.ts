import { ApiClient } from '@/api/client'
import { SessionManager } from '@/lib/utils/SessionManager'
import { StateManager } from '@/lib/utils/StateManager'
import { MemoryCache } from '@/lib/utils/cache/MemoryCache'
import type { InsightQuery } from '@/schema/query'
import type { Context } from '@/tools/types'
import { expect } from 'vitest'

export const API_BASE_URL = process.env.TEST_POSTHOG_API_BASE_URL || 'http://localhost:8010'
export const API_TOKEN = process.env.TEST_POSTHOG_PERSONAL_API_KEY
export const TEST_ORG_ID = process.env.TEST_ORG_ID
export const TEST_PROJECT_ID = process.env.TEST_PROJECT_ID

export interface CreatedResources {
    featureFlags: number[]
    insights: number[]
    dashboards: number[]
    surveys: string[]
}

export function validateEnvironmentVariables() {
    if (!API_TOKEN) {
        throw new Error('TEST_POSTHOG_PERSONAL_API_KEY environment variable is required')
    }

    if (!TEST_ORG_ID) {
        throw new Error('TEST_ORG_ID environment variable is required')
    }

    if (!TEST_PROJECT_ID) {
        throw new Error('TEST_PROJECT_ID environment variable is required')
    }
}

export function createTestClient(): ApiClient {
    return new ApiClient({
        apiToken: API_TOKEN!,
        baseUrl: API_BASE_URL,
    })
}

export function createTestContext(client: ApiClient): Context {
    const cache = new MemoryCache<any>('test-user')
    const stateManager = new StateManager(cache, client)

    const context: Context = {
        api: client,
        cache,
        env: {} as any,
        stateManager,
        sessionManager: new SessionManager(cache),
    }

    return context
}

export async function setActiveProjectAndOrg(context: Context, projectId: string, orgId: string) {
    const cache = context.cache
    await cache.set('projectId', projectId)
    await cache.set('orgId', orgId)
}

export async function cleanupResources(
    client: ApiClient,
    projectId: string,
    resources: CreatedResources
) {
    for (const flagId of resources.featureFlags) {
        try {
            await client.featureFlags({ projectId }).delete({ flagId })
        } catch (error) {
            console.warn(`Failed to cleanup feature flag ${flagId}:`, error)
        }
    }
    resources.featureFlags = []

    for (const insightId of resources.insights) {
        try {
            await client.insights({ projectId }).delete({ insightId })
        } catch (error) {
            console.warn(`Failed to cleanup insight ${insightId}:`, error)
        }
    }
    resources.insights = []

    for (const dashboardId of resources.dashboards) {
        try {
            await client.dashboards({ projectId }).delete({ dashboardId })
        } catch (error) {
            console.warn(`Failed to cleanup dashboard ${dashboardId}:`, error)
        }
    }
    resources.dashboards = []

    for (const surveyId of resources.surveys) {
        try {
            await client.surveys({ projectId }).delete({ surveyId, softDelete: false })
        } catch (error) {
            console.warn(`Failed to cleanup survey ${surveyId}:`, error)
        }
    }
    resources.surveys = []
}

export function parseToolResponse(result: any) {
    expect(result.content).toBeDefined()
    expect(result.content[0].type).toBe('text')
    return JSON.parse(result.content[0].text)
}

export function generateUniqueKey(prefix: string): string {
    return `${prefix}-${Date.now()}-${Math.random().toString(36).substring(7)}`
}

type SampleHogQLQuery = 'pageviews' | 'topEvents'

export const SAMPLE_HOGQL_QUERIES: Record<SampleHogQLQuery, InsightQuery> = {
    pageviews: {
        kind: 'DataVisualizationNode',
        source: {
            kind: 'HogQLQuery',
            query: "SELECT event, count() AS event_count FROM events WHERE timestamp >= now() - INTERVAL 7 DAY AND event = '$pageview' GROUP BY event ORDER BY event_count DESC LIMIT 10",
            filters: {
                dateRange: {
                    date_from: '-7d',
                    date_to: '-1d',
                },
            },
        },
    },
    topEvents: {
        kind: 'DataVisualizationNode',
        source: {
            kind: 'HogQLQuery',
            query: 'SELECT event, count() AS event_count FROM events WHERE timestamp >= now() - INTERVAL 7 DAY GROUP BY event ORDER BY event_count DESC LIMIT 10',
            filters: {
                dateRange: {
                    date_from: '-7d',
                    date_to: '-1d',
                },
            },
        },
    },
}

type SampleTrendQuery =
    | 'basicPageviews'
    | 'uniqueUsers'
    | 'multipleEvents'
    | 'withBreakdown'
    | 'withPropertyFilter'

export const SAMPLE_TREND_QUERIES: Record<SampleTrendQuery, InsightQuery> = {
    basicPageviews: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Page Views',
                    math: 'total',
                },
            ],
            dateRange: {
                date_from: '-7d',
                date_to: null,
            },
            interval: 'day',
            properties: [],
            filterTestAccounts: false,
        },
    },
    uniqueUsers: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Unique Users',
                    math: 'dau',
                },
            ],
            dateRange: {
                date_from: '-30d',
                date_to: null,
            },
            interval: 'day',
            properties: [],
            filterTestAccounts: true,
        },
    },
    multipleEvents: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Page Views',
                    math: 'total',
                },
                {
                    kind: 'EventsNode',
                    event: 'button_clicked',
                    custom_name: 'Button Clicks',
                    math: 'total',
                },
            ],
            dateRange: {
                date_from: '-14d',
                date_to: null,
            },
            interval: 'day',
            properties: [],
            filterTestAccounts: false,
        },
    },
    withBreakdown: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Page Views by Browser',
                    math: 'total',
                },
            ],
            breakdownFilter: {
                breakdown_type: 'event',
                breakdown: '$browser',
                breakdown_limit: 10,
            },
            dateRange: {
                date_from: '-7d',
                date_to: null,
            },
            interval: 'day',
            properties: [],
            filterTestAccounts: false,
        },
    },
    withPropertyFilter: {
        kind: 'InsightVizNode',
        source: {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Chrome/Safari Page Views',
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
            dateRange: {
                date_from: '-7d',
                date_to: null,
            },
            interval: 'day',
            properties: [],
            filterTestAccounts: false,
        },
    },
}

type SampleFunnelQuery =
    | 'basicFunnel'
    | 'strictOrderFunnel'
    | 'funnelWithBreakdown'
    | 'conversionWindow'
    | 'onboardingFunnel'

export const SAMPLE_FUNNEL_QUERIES: Record<SampleFunnelQuery, InsightQuery> = {
    basicFunnel: {
        kind: 'InsightVizNode',
        source: {
            kind: 'FunnelsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Page View',
                },
                {
                    kind: 'EventsNode',
                    event: 'button_clicked',
                    custom_name: 'Button Clicked',
                },
            ],
            dateRange: {
                date_from: '-7d',
                date_to: null,
            },
            properties: [],
            filterTestAccounts: false,
        },
    },
    strictOrderFunnel: {
        kind: 'InsightVizNode',
        source: {
            kind: 'FunnelsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Landing Page View',
                },
                {
                    kind: 'EventsNode',
                    event: 'sign_up_started',
                    custom_name: 'Sign Up Started',
                },
                {
                    kind: 'EventsNode',
                    event: 'sign_up_completed',
                    custom_name: 'Sign Up Completed',
                },
            ],
            funnelsFilter: {
                layout: 'vertical',
                breakdownAttributionType: 'first_touch',
                funnelOrderType: 'strict',
                funnelVizType: 'steps',
                funnelWindowInterval: 7,
                funnelWindowIntervalUnit: 'day',
                funnelStepReference: 'total',
            },
            dateRange: {
                date_from: '-30d',
                date_to: null,
            },
            properties: [],
            filterTestAccounts: false,
        },
    },
    funnelWithBreakdown: {
        kind: 'InsightVizNode',
        source: {
            kind: 'FunnelsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Product Page View',
                },
                {
                    kind: 'EventsNode',
                    event: 'purchase',
                    custom_name: 'Purchase',
                },
            ],
            breakdownFilter: {
                breakdown_type: 'event',
                breakdown: '$browser',
                breakdown_limit: 5,
            },
            funnelsFilter: {
                layout: 'vertical',
                breakdownAttributionType: 'first_touch',
                funnelOrderType: 'ordered',
                funnelVizType: 'steps',
                funnelWindowInterval: 14,
                funnelWindowIntervalUnit: 'day',
                funnelStepReference: 'total',
            },
            dateRange: {
                date_from: '-14d',
                date_to: null,
            },
            properties: [],
            filterTestAccounts: false,
        },
    },
    conversionWindow: {
        kind: 'InsightVizNode',
        source: {
            kind: 'FunnelsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    custom_name: 'Page View',
                },
                {
                    kind: 'EventsNode',
                    event: 'add_to_cart',
                    custom_name: 'Add to Cart',
                },
                {
                    kind: 'EventsNode',
                    event: 'purchase',
                    custom_name: 'Purchase',
                },
            ],
            funnelsFilter: {
                layout: 'vertical',
                breakdownAttributionType: 'first_touch',
                funnelOrderType: 'ordered',
                funnelVizType: 'steps',
                funnelWindowInterval: 1,
                funnelWindowIntervalUnit: 'hour',
                funnelStepReference: 'total',
            },
            dateRange: {
                date_from: '-7d',
                date_to: null,
            },
            properties: [],
            filterTestAccounts: false,
        },
    },
    onboardingFunnel: {
        kind: 'InsightVizNode',
        source: {
            kind: 'FunnelsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: 'Signed In',
                    custom_name: 'User Signs In',
                },
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    properties: [
                        {
                            key: '$pathname',
                            type: 'event',
                            value: 'get-started',
                            operator: 'icontains',
                        },
                    ],
                    custom_name: 'Views Get-Started Page',
                },
                {
                    kind: 'EventsNode',
                    event: 'Integration Connected',
                    custom_name: 'Connects Integration',
                },
                {
                    kind: 'EventsNode',
                    event: 'Onboarding Completed',
                    custom_name: 'Completes Onboarding',
                },
            ],
            dateRange: {
                date_to: 'today',
                date_from: '-30d',
            },
            funnelsFilter: {
                layout: 'vertical',
                breakdownAttributionType: 'first_touch',
                funnelOrderType: 'ordered',
                funnelVizType: 'steps',
                funnelWindowInterval: 24,
                funnelWindowIntervalUnit: 'hour',
                funnelStepReference: 'total',
            },
            properties: [],
            filterTestAccounts: true,
        },
    },
}
