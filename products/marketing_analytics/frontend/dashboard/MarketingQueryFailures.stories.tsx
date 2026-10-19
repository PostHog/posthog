import { Meta, StoryObj } from '@storybook/react'

import { AttributionTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable'
import { ConversionPaths } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/ConversionPaths'
import { MarketingAnalyticsOverview } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsOverview/MarketingAnalyticsOverview'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

import { RetentionResults } from '../retention/RetentionResults'
import { ConversionValueLoaded } from './cards/ConversionValueLoaded'
import { RetentionCards } from './cards/RetentionCards'
import { RevenueValueCard } from './cards/RevenueValueCard'

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

const valueQuery: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [{ kind: NodeKind.EventsNode, event: 'purchase', math: PropertyMathType.Sum, math_property: 'amount' }],
}

export const RevenueCardFailure: Story = {
    decorators: [failedQuery],
    render: () => (
        <div className="w-240 max-w-full">
            <RevenueValueCard query={valueQuery} />
        </div>
    ),
}

export const ConversionValueCardsFailure: Story = {
    decorators: [failedQuery],
    render: () => (
        <div className="w-240 max-w-full">
            <ConversionValueLoaded query={valueQuery} keys={['conversion_value', 'avg_conversion_value']} />
        </div>
    ),
}

export const RetentionCardsFailure: Story = {
    decorators: [failedQuery],
    render: () => (
        <div className="w-240 max-w-full">
            <RetentionCards />
        </div>
    ),
}
