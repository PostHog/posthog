import { Meta, StoryObj } from '@storybook/react'

import { AttributionTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable'
import { ConversionPaths } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/ConversionPaths'
import { MarketingAnalyticsOverview } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsOverview/MarketingAnalyticsOverview'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import { RetentionResults } from '../retention/RetentionResults'

const meta: Meta = { title: 'Marketing Analytics/Failed queries' }
export default meta
type Story = StoryObj<typeof meta>

const failedQuery = mswDecorator({
    post: {
        '/api/environments/:team_id/query/:kind/': [500, { type: 'server_error', detail: 'Could not run this query.' }],
    },
})

export const OverviewQueryFailure: Story = {
    decorators: [failedQuery],
    render: () => (
        <MarketingAnalyticsOverview
            query={{ kind: NodeKind.MarketingAnalyticsAggregatedQuery, properties: [] }}
            context={{}}
        />
    ),
}

export const AttributionQueryFailure: Story = {
    decorators: [failedQuery],
    render: () => (
        <AttributionTable
            query={{
                kind: NodeKind.MarketingAnalyticsAttributionQuery,
                conversionGoalId: 'example-goal',
                properties: [],
            }}
        />
    ),
}

export const ConversionPathsQueryFailure: Story = {
    decorators: [failedQuery],
    render: () => (
        <ConversionPaths
            query={{
                kind: NodeKind.MarketingAnalyticsAttributionPathsQuery,
                conversionGoalId: 'example-goal',
                properties: [],
            }}
        />
    ),
}

export const RetentionQueryFailure: Story = {
    decorators: [failedQuery],
    render: () => <RetentionResults query={{ kind: NodeKind.MarketingAnalyticsRetentionQuery, properties: [] }} />,
}
