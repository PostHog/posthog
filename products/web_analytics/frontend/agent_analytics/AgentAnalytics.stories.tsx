import { Meta } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { WebAgentAnalyticsQueryType } from '~/queries/schema/schema-general'

const overviewResponse = {
    columns: [
        'active_clients',
        'agent_families',
        'server_requests',
        'client_navigations',
        'status_observed',
        'client_errors',
        'active_clients_prev',
        'server_requests_prev',
        'client_navigations_prev',
        'client_errors_prev',
        'malformed',
        'malformed_prev',
        'llms_txt_fetches',
        'excluded_requests',
        'wasted',
        'wasted_prev',
        'waste_pages',
        'converted_agents',
        'converted_agents_prev',
    ],
    results: [[128, 4, 2460, 310, 2460, 83, 104, 2210, 270, 99, 5, 3, 42, 190, 61, 74, 4, 14, 9]],
}

const issuesResponse = {
    columns: ['intent_key', 'intent_path', 'demand', 'demand_prev', 'variants', 'top_agent', 'first_seen', 'last_seen'],
    results: [
        [
            'example.com/guides/access-tokens',
            '/guides/access-tokens',
            48,
            39,
            3,
            'Claude-User',
            '2026-08-13 10:00:00',
            '2026-08-19 12:00:00',
        ],
        [
            'example.com/reference/file-uploads',
            '/reference/file-uploads',
            31,
            28,
            2,
            'ChatGPT-User',
            '2026-08-14 09:00:00',
            '2026-08-19 11:00:00',
        ],
    ],
}

const pagesResponse = {
    columns: ['page', 'fetches', 'md_fetches', 'html_fetches', 'paired_clients'],
    results: [
        ['example.com/guides/getting-started', 420, 280, 140, 18],
        ['example.com/reference/imports', 310, 62, 248, 7],
        ['example.com/pricing', 205, 0, 205, 0],
    ],
}

const nextHopsResponse = {
    columns: ['next_path', 'requests', 'not_found'],
    results: [
        ['/guides/getting-started', 74, 0],
        ['/reference/imports', 41, 0],
        ['/guides/access-tokens', 26, 26],
    ],
}

const demandResponse = {
    columns: ['page', 'host', 'path', 'demand'],
    results: [
        ['example.com/guides/getting-started', 'example.com', '/guides/getting-started', 420],
        ['example.com/reference/imports', 'example.com', '/reference/imports', 310],
        ['example.com/pricing', 'example.com', '/pricing', 205],
    ],
}

const variantsResponse = {
    columns: ['variant', 'demand', 'top_agent', 'first_seen'],
    results: [
        ['/guides/access-tokens', 29, 'Claude User', '2026-08-13 10:00:00'],
        ['/guides/access-tokens.md', 14, 'ChatGPT', '2026-08-15 11:00:00'],
        ['/guides/access-tokens-v2', 5, 'Claude User', '2026-08-18 08:00:00'],
    ],
}

const requestAnatomyResponse = {
    columns: ['agent', 'requests', 'requested_markdown', 'retry_pairs', 'errors'],
    results: [
        ['Claude User', 120, 72, 18, 4],
        ['ChatGPT User', 100, 35, 7, 8],
    ],
}

const journeySummaryResponse = {
    columns: ['total_journeys', 'median_pages', 'median_requests', 'median_duration_seconds', 'journeys_with_errors'],
    results: [[84, 3, 5, 72, 19]],
}

interface MockQueryResponse {
    columns: string[]
    results: unknown[][]
    hasMore?: boolean
}

const paginatedResponse = (response: MockQueryResponse, offset?: number): MockQueryResponse =>
    offset ? { ...response, results: response.results.slice(-1), hasMore: false } : { ...response, hasMore: true }

const journeysResponse = {
    columns: ['journey_key', 'started', 'agent', 'host', 'pages', 'requests', 'duration_seconds', 'errors'],
    results: [
        ['journey-example', '2026-08-19 14:02:01', 'Claude User', 'example.com', 4, 7, 11, 2],
        ['journey-inferred', '2026-08-19 13:44:12', 'ChatGPT User', 'example.com', 3, 4, 38, 0],
    ],
    hasMore: true,
}

const journeysNextPageResponse = {
    ...journeysResponse,
    results: [['journey-older', '2026-08-18 09:20:00', 'Claude User', 'docs.example.com', 2, 3, 19, 0]],
    hasMore: false,
}

const journeyDetailResponse = {
    columns: ['timestamp', 'path', 'status', 'format', 'referrer', 'transition'],
    results: [
        ['2026-08-19 14:02:01', '/llms.txt', 200, 'html', '', 'start'],
        ['2026-08-19 14:02:04', '/guides/getting-started', 200, 'html', 'https://example.com/llms.txt', 'confirmed'],
        ['2026-08-19 14:02:05', '/guides/getting-started.md', 200, 'markdown', '', 'sequential'],
        ['2026-08-19 14:02:09', '/guides/access-tokens', 404, 'html', '', 'sequential'],
        ['2026-08-19 14:02:09', '/guides/access-tokens.md', 404, 'markdown', '', 'parallel'],
    ],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Web Analytics/Agent analytics',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-08-19',
        pageUrl: urls.webAnalyticsAgents(),
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_AGENT_ANALYTICS, FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2],
        testOptions: {
            includeNavigationInSnapshot: true,
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 128 }],
                '/api/projects/:team_id/event_definitions': () => [200, { count: 5 }],
                '/api/projects/:team_id/health_issues/': () => [200, { results: [] }],
                '/api/environments/:team_id/health_issues/summary/': () => [200, {}],
            },
            post: {
                '/api/projects/:team_id/web_analytics/llms_txt/': () => [
                    200,
                    {
                        content: [
                            '# Example documentation',
                            '- [Getting started](https://example.com/guides/getting-started)',
                            '- [Pricing](https://example.com/pricing)',
                        ].join('\n'),
                        url: 'https://example.com/llms.txt',
                    },
                ],
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    interface MockQuerySource {
                        kind?: string
                        queryType?: WebAgentAnalyticsQueryType
                        offset?: number
                    }
                    const requestBody = (await request.json()) as {
                        query?: MockQuerySource & { source?: MockQuerySource }
                    }
                    const source = requestBody.query?.source ?? requestBody.query

                    if (source?.kind === 'DatabaseSchemaQuery') {
                        return [200, { tables: {}, joins: [] }]
                    }
                    switch (source?.queryType) {
                        case WebAgentAnalyticsQueryType.Overview:
                            return [200, overviewResponse]
                        case WebAgentAnalyticsQueryType.Issues:
                            return [200, paginatedResponse(issuesResponse, source.offset)]
                        case WebAgentAnalyticsQueryType.PageRequests:
                            return [200, pagesResponse]
                        case WebAgentAnalyticsQueryType.Transitions:
                            return [200, paginatedResponse(nextHopsResponse, source.offset)]
                        case WebAgentAnalyticsQueryType.Demand:
                            return [200, paginatedResponse(demandResponse, source.offset)]
                        case WebAgentAnalyticsQueryType.IssueVariants:
                            return [200, paginatedResponse(variantsResponse, source.offset)]
                        case WebAgentAnalyticsQueryType.RequestAnatomy:
                            return [200, paginatedResponse(requestAnatomyResponse, source.offset)]
                        case WebAgentAnalyticsQueryType.JourneySummary:
                            return [200, journeySummaryResponse]
                        case WebAgentAnalyticsQueryType.Journeys:
                            return [200, source.offset ? journeysNextPageResponse : journeysResponse]
                        case WebAgentAnalyticsQueryType.JourneyDetail:
                            return [200, journeyDetailResponse]
                    }
                    return [200, { columns: [], results: [] }]
                },
            },
        }),
    ],
}

export default meta

export function AgentAnalyticsOverview(): JSX.Element {
    return <App />
}

AgentAnalyticsOverview.parameters = {
    pageUrl: `${urls.webAnalyticsAgents()}?conversionGoal.customEventName=completed_signup`,
}

export function AgentAnalyticsReadiness(): JSX.Element {
    return <App />
}

AgentAnalyticsReadiness.parameters = {
    pageUrl: `${urls.webAnalyticsAgents()}?view=readiness&conversionGoal.customEventName=completed_signup`,
}

export function AgentAnalyticsJourneys(): JSX.Element {
    return <App />
}

AgentAnalyticsJourneys.parameters = {
    pageUrl: `${urls.webAnalyticsAgents()}?view=journeys`,
}

export function AgentAnalyticsIssues(): JSX.Element {
    return <App />
}

AgentAnalyticsIssues.parameters = {
    pageUrl: `${urls.webAnalyticsAgents()}?view=issues`,
}

export function AgentAnalyticsJourneyDetail(): JSX.Element {
    return <App />
}

AgentAnalyticsJourneyDetail.parameters = {
    pageUrl: `${urls.webAnalyticsAgents()}?view=journeys&journey=journey-example`,
}

export function AgentAnalyticsIssueDetail(): JSX.Element {
    return <App />
}

AgentAnalyticsIssueDetail.parameters = {
    pageUrl: `${urls.webAnalyticsAgents()}?view=issues&issue=${encodeURIComponent('example.com/guides/access-tokens')}`,
}
