import type { Meta, StoryObj } from '@storybook/react'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { InsightDashboardFiltersBanner } from './InsightDashboardFiltersBanner'

const query = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        dateRange: { date_from: '-30d' },
        interval: 'day',
    },
} satisfies InsightVizNode

const meta: Meta<typeof InsightDashboardFiltersBanner> = {
    title: 'Scenes-App/Insights/Insight dashboard filters banner',
    component: InsightDashboardFiltersBanner,
    args: {
        insightId: 'example',
        dashboardId: 1,
        query,
        filtersOverride: {
            date_from: '-7d',
            interval: 'week',
            properties: [
                {
                    key: '$browser',
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                    value: ['Chrome'],
                },
            ],
        },
    },
}
export default meta

type Story = StoryObj<typeof InsightDashboardFiltersBanner>

export const DashboardFilters: Story = {}

export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}

export const TileFilters: Story = {
    args: {
        tileFiltersOverride: { date_from: '-14d', filterTestAccounts: false },
    },
}
