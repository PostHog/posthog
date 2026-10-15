import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { SourceTab, TileId } from 'scenes/web-analytics/common'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { mswDecorator } from '~/mocks/browser'
import { WebStatsBreakdown } from '~/queries/schema/schema-general'

function SourcesExample({ tab = SourceTab.CHANNEL }: { tab?: SourceTab }): JSX.Element | null {
    const { tiles } = useValues(webAnalyticsLogic)
    const sources = tiles.find((tile) => tile.tileId === TileId.SOURCES)
    const selected = sources?.kind === 'tabs' ? sources.tabs.find((item) => item.id === tab) : undefined
    return selected ? (
        <WebQuery
            query={selected.query}
            insightProps={selected.insightProps}
            tileId={TileId.SOURCES}
            uniqueKey={`WebAnalytics.${TileId.SOURCES}.${tab}`}
            headerSlot={
                <div className="px-4 pt-4">
                    <h3>Sources</h3>
                    <LemonTabs
                        activeKey={tab}
                        tabs={[
                            { key: SourceTab.CHANNEL, label: 'Channel' },
                            { key: SourceTab.UTM_SOURCE, label: 'UTM source' },
                            { key: SourceTab.UTM_CAMPAIGN, label: 'UTM campaign' },
                        ]}
                    />
                </div>
            }
        />
    ) : null
}

const meta: Meta<typeof SourcesExample> = {
    title: 'Web Analytics/Marketing cross sell',
    component: SourcesExample,
    parameters: {
        layout: 'fullscreen',
        featureFlags: { [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL]: true },
    },
    decorators: [
        (Story) => (
            <div className="max-w-160 p-4">
                <Story />
            </div>
        ),
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { breakdownBy: WebStatsBreakdown } }
                    const names =
                        query.breakdownBy === WebStatsBreakdown.InitialUTMSource
                            ? ['google', 'facebook', 'newsletter']
                            : query.breakdownBy === WebStatsBreakdown.InitialUTMCampaign
                              ? ['brand_search', 'product_launch', 'weekly_newsletter']
                              : ['Organic Search', 'Paid Search', 'Direct']
                    return [
                        200,
                        {
                            columns: [
                                'context.columns.breakdown_value',
                                'context.columns.visitors',
                                'context.columns.views',
                            ],
                            results: names.map((name, index) => [
                                name,
                                [4800 - index * 1200, null],
                                [7200 - index * 1600, null],
                            ]),
                            hasMore: false,
                        },
                    ]
                },
            },
            get: {
                '/api/projects/:team_id/external_data_sources/': { results: [], next: null, count: 0 },
                '/api/projects/:team_id/health_issues/': { results: [], next: null, count: 0 },
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof SourcesExample>
export const Channel: Story = {}
export const Source: Story = { args: { tab: SourceTab.UTM_SOURCE } }
export const Campaign: Story = { args: { tab: SourceTab.UTM_CAMPAIGN } }
export const Connected: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/external_data_sources/': {
                    results: [{ id: 'example-google-ads', source_type: 'GoogleAds' }],
                    next: null,
                    count: 1,
                },
            },
        }),
    ],
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-96">
                <Story />
            </div>
        ),
    ],
}
export const FlagOff: Story = {
    parameters: { featureFlags: { [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING_CROSS_SELL]: false } },
}
