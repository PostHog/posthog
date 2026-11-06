import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { mswDecorator } from '~/mocks/browser'
import funnelTopToBottom from '~/mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import lifecycle from '~/mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import stickiness from '~/mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import trendsBarBreakdown from '~/mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsLine from '~/mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import trendsNumber from '~/mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import { NodeKind } from '~/queries/schema/schema-general'
import { BaseMathType, ChartDisplayType, PropertyMathType } from '~/types'

import { realisticRetentionResult } from 'products/product_analytics/frontend/insights/retention/shared/retentionStoryFixtures'

import { HomeTabDefault } from './HomeTabDefault'

interface StoryQuery {
    kind?: NodeKind
    source?: StoryQuery
    series?: { math?: string }[]
    trendsFilter?: { display?: ChartDisplayType }
    breakdownFilter?: { breakdown?: string }
}

const statValues: Record<string, number> = {
    [BaseMathType.UniqueUsers]: 4268,
    [BaseMathType.UniqueSessions]: 6132,
    [BaseMathType.FirstTimeForUser]: 1375,
    [PropertyMathType.Average]: 184,
}

const trendDays = Array.from({ length: 30 }, (_, index) => {
    const date = new Date(Date.UTC(2023, 5, 12 + index))
    return date.toISOString().slice(0, 10)
})
const trendData = trendDays.map((_, index) => Math.round(510 + index * 11 + [18, -12, 7, 28, 4, -26, -16][index % 7]))

function rankedResults(names: string[], counts: number[]): unknown[] {
    return names.map((name, index) => ({
        ...trendsBarBreakdown.result[0],
        label: name,
        breakdown_value: name,
        count: counts[index],
        aggregated_value: counts[index],
        data: [counts[index]],
        days: [trendDays[trendDays.length - 1]],
        labels: ['Jul 11'],
    }))
}

async function homeQueryMock({
    request,
}: {
    request: Request
}): Promise<[number, { results: unknown[]; columns?: string[]; types?: string[][] }]> {
    const body = (await request.json()) as { query?: StoryQuery }
    const query = body.query?.source ?? body.query

    if (query?.kind === NodeKind.RetentionQuery) {
        return [200, { results: realisticRetentionResult }]
    }
    if (query?.kind === NodeKind.LifecycleQuery) {
        return [200, { results: lifecycle.result }]
    }
    if (query?.kind === NodeKind.StickinessQuery) {
        return [200, { results: stickiness.result }]
    }
    if (query?.kind === NodeKind.FunnelsQuery) {
        return [200, { results: funnelTopToBottom.result }]
    }
    if (query?.kind === NodeKind.HogQLQuery) {
        return [
            200,
            {
                columns: ['event', 'people', 'share'],
                types: [
                    ['event', 'String'],
                    ['people', 'UInt64'],
                    ['share', 'Float64'],
                ],
                results: [
                    ['downloaded_file', 1793, 0.42],
                    ['uploaded_file', 1152, 0.27],
                    ['signed_up', 768, 0.18],
                    ['shared_file', 384, 0.09],
                ],
            },
        ]
    }

    if (query?.trendsFilter?.display === ChartDisplayType.BoldNumber) {
        const value = statValues[query.series?.[0]?.math ?? ''] ?? 4268
        return [
            200,
            {
                results: [
                    { ...trendsNumber.result[0], aggregated_value: value },
                    { ...trendsNumber.result[0], aggregated_value: Math.round(value * 0.84) },
                ],
            },
        ]
    }

    if (query?.trendsFilter?.display === ChartDisplayType.WorldMap) {
        return [
            200,
            {
                results: rankedResults(
                    ['US', 'GB', 'DE', 'FR', 'IN', 'AU', 'BR', 'CA', 'JP'],
                    [1540, 620, 490, 380, 340, 260, 220, 210, 180]
                ),
            },
        ]
    }
    if (query?.trendsFilter?.display === ChartDisplayType.ActionsDonut) {
        return [200, { results: rankedResults(['Desktop', 'Mobile', 'Tablet'], [3820, 1980, 332]) }]
    }
    if (query?.trendsFilter?.display === ChartDisplayType.ActionsBarValue) {
        if (query.breakdownFilter?.breakdown === '$pathname') {
            return [
                200,
                {
                    results: rankedResults(
                        ['/', '/pricing', '/docs', '/signup', '/blog'],
                        [4821, 3204, 2450, 1673, 1196]
                    ),
                },
            ]
        }
        if (query.breakdownFilter?.breakdown === '$screen_name') {
            return [
                200,
                { results: rankedResults(['Home', 'Explore', 'Settings', 'Profile'], [3320, 2310, 1484, 956]) },
            ]
        }
        return [
            200,
            {
                results: rankedResults(
                    ['$pageview', '$autocapture', '$screen', 'signup', 'purchase'],
                    [9204, 5432, 3187, 1268, 793]
                ),
            },
        ]
    }

    const scale =
        query?.series?.[0]?.math === BaseMathType.UniqueSessions
            ? 1.45
            : query?.series?.[0]?.math === BaseMathType.FirstTimeForUser
              ? 0.4
              : query?.series?.[0]?.math === PropertyMathType.Average
                ? 0.3
                : 1
    return [
        200,
        {
            results: [
                {
                    ...trendsLine.result[0],
                    label: 'Activity',
                    data: trendData.map((value) => Math.round(value * scale)),
                    days: trendDays,
                    labels: trendDays.map((day) => day.slice(5)),
                    count: Math.round(trendData.reduce((sum, value) => sum + value, 0) * scale),
                },
            ],
        },
    ]
}

const meta: Meta<typeof HomeTabDefault> = {
    component: HomeTabDefault,
    title: 'Scenes-App/Product analytics home overview',
    parameters: {
        layout: 'fullscreen',
        mockDate: '2023-07-11',
        testOptions: { viewport: { width: 1440, height: 1200 }, waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': homeQueryMock,
                '/api/environments/:team_id/query/:query_kind/': homeQueryMock,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof HomeTabDefault>

export const Populated: Story = {
    render: () => (
        <div className="@container/main-content mx-auto w-full max-w-screen-xl p-4">
            <HomeTabDefault />
        </div>
    ),
}

function viewStory(tabLabel: string): Story {
    return {
        render: Populated.render,
        parameters: {
            featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_VIEWS],
            testOptions: { viewport: { width: 1440, height: 1200 }, snapshotBrowsers: [] },
        },
        play: async ({ canvasElement }) => {
            await userEvent.click(await within(canvasElement).findByText(tabLabel))
        },
    }
}

export const NewUsersView: Story = viewStory('New users')

export const EngagementView: Story = viewStory('Engagement')

export const RetentionView: Story = viewStory('Retention')

export const Narrow: Story = {
    // A docked side panel leaves roughly 520px for the scene on a laptop.
    render: () => (
        <div className="@container/main-content mx-auto w-[520px] max-w-full p-4">
            <HomeTabDefault />
        </div>
    ),
}

export const Empty: Story = {
    render: Populated.render,
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': { results: [] },
                '/api/environments/:team_id/query/:query_kind/': { results: [] },
            },
        }),
    ],
}

export const BeforeIngestion: Story = {
    render: () => {
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: false, is_demo: false })
        return (
            <div className="@container/main-content mx-auto w-full max-w-screen-xl p-4">
                <HomeTabDefault />
            </div>
        )
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/': { results: [] },
                '/api/environments/:team_id/query/:query_kind/': { results: [] },
            },
        }),
    ],
}
