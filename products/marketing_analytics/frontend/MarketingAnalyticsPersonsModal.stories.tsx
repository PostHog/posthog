import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'
import { PersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { MarketingAnalyticsTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsTable/MarketingAnalyticsTable'
import { marketingAnalyticsSettingsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'

import { useStorybookMocks } from '~/mocks/browser'
import {
    ActorsQuery,
    AttributionMode,
    DataTableNode,
    MarketingAnalyticsDrillDownLevel,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

const meta: Meta = { title: 'Marketing Analytics/Conversion people' }
export default meta
type Story = StoryObj<typeof meta>

const tableQuery: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.MarketingAnalyticsTableQuery,
        properties: [],
        dateRange: { date_from: '-7d' },
        drillDownLevel: MarketingAnalyticsDrillDownLevel.Campaign,
        select: ['Campaign', 'Source', 'Purchases'],
    },
}

const actorsQuery: ActorsQuery = {
    kind: NodeKind.ActorsQuery,
    orderBy: ['id'],
    source: {
        kind: NodeKind.MarketingAnalyticsActorsQuery,
        source: tableQuery.source as MarketingAnalyticsTableQuery,
        conversionGoalId: 'purchases',
        breakdown: { value: 'winter-sale', source: 'google', matchKey: 'winter-sale' },
    },
}

const peopleResponse = {
    results: ['alex', 'sam', 'taylor', 'robin'].map((name, index) => [
        {
            id: `00000000-0000-4000-8000-00000000000${index + 1}`,
            distinct_ids: [`${name}@example.com`],
            is_identified: true,
            created_at: '2023-01-01T12:00:00Z',
            properties: { email: `${name}@example.com` },
        },
    ]),
    columns: ['actor'],
    hasMore: false,
}

export const WithResults: Story = {
    render: () => {
        useStorybookMocks({ post: { '/api/environments/:team_id/query/:kind/': peopleResponse } })
        return <PersonsModal title="Purchases: people attributed to winter-sale" actorsQuery={actorsQuery} inline />
    },
}

export const Preparing: Story = {
    render: () => {
        useStorybookMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': {
                    results: [],
                    columns: ['actor'],
                    precomputeNotReady: true,
                    hasMore: false,
                },
            },
        })
        return <PersonsModal title="Purchases: people attributed to winter-sale" actorsQuery={actorsQuery} inline />
    },
}

function ConversionTableStory(): JSX.Element {
    useMountedLogic(marketingAnalyticsSettingsLogic)
    useStorybookMocks({
        post: {
            '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                const { query } = (await request.json()) as { query: { kind: NodeKind } }
                return query.kind === NodeKind.ActorsQuery
                    ? peopleResponse
                    : {
                          results: [
                              [
                                  {
                                      key: 'Campaign',
                                      kind: 'unit',
                                      value: 'winter-sale',
                                      conversionMatchKey: 'winter-sale',
                                  },
                                  { key: 'Source', kind: 'unit', value: 'google' },
                                  { key: 'Purchases', kind: 'unit', value: 4 },
                              ],
                          ],
                          columns: ['Campaign', 'Source', 'Purchases'],
                          hasMore: false,
                      }
            },
        },
    })
    useEffect(() => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            marketing_analytics_config: {
                sources_map: {},
                campaign_name_mappings: {},
                custom_source_mappings: {},
                campaign_field_preferences: {},
                attribution_window_days: 30,
                attribution_mode: AttributionMode.LastTouch,
                filter_test_accounts: false,
                conversion_goals: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'purchase',
                        name: 'Purchases',
                        conversion_goal_id: 'purchases',
                        conversion_goal_name: 'Purchases',
                        math: BaseMathType.TotalCount,
                        schema_map: {},
                    },
                ],
            },
        })
        marketingAnalyticsSettingsLogic.actions.loadMarketingAnalyticsConfig()
    }, [])
    return <MarketingAnalyticsTable query={tableQuery} insightProps={{ dashboardItemId: 'new' }} />
}

export const TableFlagOff: Story = { render: () => <ConversionTableStory /> }
export const TableFlagOn: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_PEOPLE] },
    render: () => <ConversionTableStory />,
}
