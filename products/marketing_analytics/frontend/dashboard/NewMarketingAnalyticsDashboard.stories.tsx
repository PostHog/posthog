import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

const FLAGS = [
    FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
    FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD,
    FEATURE_FLAGS.MARKETING_ANALYTICS_RETENTION,
    FEATURE_FLAGS.MARKETING_ANALYTICS_ATTRIBUTION,
]

const overviewItem = (key: string, kind: string, value: number, previous: number): Record<string, unknown> => ({
    key,
    kind,
    value,
    previous,
    changeFromPreviousPct: Math.round(((value - previous) / previous) * 100),
})

const WEB_OVERVIEW = {
    results: [
        overviewItem('visitors', 'unit', 14320, 12180),
        overviewItem('views', 'unit', 41210, 36940),
        overviewItem('sessions', 'unit', 19870, 17420),
        overviewItem('session duration', 'duration_s', 184, 171),
        overviewItem('bounce rate', 'percentage', 41.2, 44.8),
    ],
}

const CONVERSION_OVERVIEW = {
    results: [
        overviewItem('visitors', 'unit', 14320, 12180),
        overviewItem('total conversions', 'unit', 1284, 1011),
        overviewItem('unique conversions', 'unit', 1150, 930),
        overviewItem('conversion rate', 'percentage', 8.03, 7.63),
    ],
}

const CHANNELS = ['Organic Search', 'Paid Search', 'Direct', 'Referral', 'Paid Social', 'Email']

/** Every metric column is [current, previous], the shape the compare cells read. */
const statsRow = (channel: string, index: number): unknown[] => {
    const visitors = 5200 - index * 700
    return [
        channel,
        [visitors, Math.round(visitors * 0.88)],
        [visitors * 2, Math.round(visitors * 1.8)],
        [Math.round(visitors * 1.3), Math.round(visitors * 1.2)],
        [210 - index * 18, 198 - index * 16],
        [0.38 + index * 0.03, 0.42 + index * 0.03],
        [Math.round(visitors * 0.09), Math.round(visitors * 0.08)],
        [Math.round(visitors * 0.08), Math.round(visitors * 0.07)],
        [0.084 - index * 0.004, 0.079 - index * 0.004],
        1 - index * 0.15,
        '',
    ]
}

const WEB_STATS = {
    columns: [
        'context.columns.breakdown_value',
        'context.columns.visitors',
        'context.columns.views',
        'context.columns.sessions',
        'context.columns.session_duration',
        'context.columns.bounce_rate',
        'context.columns.total_conversions',
        'context.columns.unique_conversions',
        'context.columns.conversion_rate',
        'context.columns.ui_fill_fraction',
        'context.columns.cross_sell',
    ],
    results: CHANNELS.map(statsRow),
}

const retentionRow = (channel: string, index: number, previous: boolean): Record<string, unknown> => {
    const acquired = (2400 - index * 320) * (previous ? 0.9 : 1)
    return {
        breakdownValue: channel,
        previous,
        acquired: Math.round(acquired),
        eligible7d: Math.round(acquired * 0.9),
        returned7d: Math.round(acquired * 0.32),
        eligible30d: Math.round(acquired * 0.7),
        returned30d: Math.round(acquired * 0.48),
        returners: Math.round(acquired * 0.48),
        medianReturnDays: 3.4 + index * 0.6,
    }
}

const RETENTION = {
    summary: [
        ...CHANNELS.map((channel, index) => retentionRow(channel, index, false)),
        ...CHANNELS.map((channel, index) => retentionRow(channel, index, true)),
    ],
}

const REVENUE = {
    results: [
        { aggregated_value: 184320, compare_label: 'current' },
        { aggregated_value: 151980, compare_label: 'previous' },
    ],
}

/** The seven days ending on the story's mocked date, the range "Last 7 days" resolves to. */
const CHART_DAYS = Array.from({ length: 7 }, (_, index) => `2026-09-${String(10 + index).padStart(2, '0')}`)

const chartSeries = (label: string, base: number, breakdownValue?: string): Record<string, unknown> => ({
    label,
    days: CHART_DAYS,
    data: CHART_DAYS.map((_, index) => Math.round(base * (1 + index * 0.06))),
    ...(breakdownValue === undefined ? {} : { breakdown_value: breakdownValue }),
})

const CHART_TOTAL = { results: [chartSeries('Visitors', 2040)] }

const CHART_BREAKDOWN = {
    results: CHANNELS.map((channel, index) => chartSeries(channel, 740 - index * 100, channel)),
}

const MARKETING_CONFIG = {
    conversion_goals: [
        {
            kind: NodeKind.EventsNode,
            event: 'signed_up',
            conversion_goal_id: 'signups',
            conversion_goal_name: 'Sign ups',
            schema_map: {},
            counts_as_customer: true,
        },
        {
            kind: NodeKind.EventsNode,
            event: 'purchase',
            conversion_goal_id: 'purchases',
            conversion_goal_name: 'Purchases',
            schema_map: {},
            counts_as_revenue: true,
            math: 'sum',
            math_property: 'revenue',
        },
    ],
}

const queryMock = async ({ request }: { request: Request }): Promise<[number, Record<string, unknown>]> => {
    const body = (await request.json()) as {
        query?: {
            kind?: string
            conversionGoal?: unknown
            breakdownFilter?: unknown
            trendsFilter?: { display?: string }
        }
    }
    const query = body?.query
    switch (query?.kind) {
        case NodeKind.WebOverviewQuery:
            return [200, query.conversionGoal ? CONVERSION_OVERVIEW : WEB_OVERVIEW]
        case NodeKind.WebStatsTableQuery:
            return [200, WEB_STATS]
        case NodeKind.MarketingAnalyticsRetentionQuery:
            return [200, RETENTION]
        case NodeKind.TrendsQuery:
            // The cards ask for a single aggregate; only the expanded metric chart draws a line.
            if (query.trendsFilter?.display !== ChartDisplayType.ActionsLineGraph) {
                return [200, REVENUE]
            }
            return [200, query.breakdownFilter ? CHART_BREAKDOWN : CHART_TOTAL]
        default:
            return [200, { results: [] }]
    }
}

const teamMock = (): [number, Record<string, unknown>] => [
    200,
    { ...MOCK_DEFAULT_TEAM, marketing_analytics_config: MARKETING_CONFIG },
]

const meta: Meta = {
    title: 'Scenes-App/Marketing Analytics/New dashboard',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-16',
        pageUrl: urls.marketingAnalyticsApp(),
        featureFlags: FLAGS,
    },
    decorators: [
        mswDecorator({
            get: {
                // The bootstrap endpoints teamLogic reads, which take the literal @current.
                '/api/environments/@current/': teamMock,
                '/api/projects/@current/': teamMock,
                '/api/environments/@current': teamMock,
                '/api/environments/:team_id/': teamMock,
                '/api/projects/:team_id/': teamMock,
            },
            post: {
                // The client puts the query kind in the path, so the pattern needs the segment.
                '/api/environments/:team_id/query/:kind/': queryMock,
                '/api/environments/:team_id/query/:kind': queryMock,
                '/api/environments/:team_id/query/': queryMock,
            },
        }),
    ],
}
export default meta

export function Overview(): JSX.Element {
    return <WithGoals />
}

export function Acquisition(): JSX.Element {
    return <WithGoals />
}
Acquisition.parameters = { pageUrl: `${urls.marketingAnalyticsApp()}?view=acquisition`, featureFlags: FLAGS }

export function Engagement(): JSX.Element {
    return <WithGoals />
}
Engagement.parameters = { pageUrl: `${urls.marketingAnalyticsApp()}?view=engagement`, featureFlags: FLAGS }

export function Retention(): JSX.Element {
    return <WithGoals />
}
Retention.parameters = { pageUrl: `${urls.marketingAnalyticsApp()}?view=retention`, featureFlags: FLAGS }

/** Storybook preloads the team from POSTHOG_APP_CONTEXT, so the goals have to be seeded through
 * the logic rather than an endpoint mock. */
function WithGoals(): JSX.Element {
    const { loadCurrentTeamSuccess } = useActions(teamLogic)
    useEffect(() => {
        loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, marketing_analytics_config: MARKETING_CONFIG } as never)
    }, [loadCurrentTeamSuccess])
    return <App />
}

export function Conversion(): JSX.Element {
    return <WithGoals />
}
Conversion.parameters = { pageUrl: `${urls.marketingAnalyticsApp()}?view=conversion`, featureFlags: FLAGS }

/** The scene keeps about 520px once the nav and an open side panel take their share, so this is
 * the width the layout has to survive. */
export function Narrow(): JSX.Element {
    return (
        <div className="w-[520px] border-x">
            <WithGoals />
        </div>
    )
}
Narrow.parameters = { layout: 'padded', pageUrl: urls.marketingAnalyticsApp(), featureFlags: FLAGS }

export function AllTime(): JSX.Element {
    return <WithGoals />
}
AllTime.parameters = { pageUrl: `${urls.marketingAnalyticsApp()}?date_from=all`, featureFlags: FLAGS }
