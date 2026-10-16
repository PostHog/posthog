import '~/queries/nodes/InsightViz/InsightViz.scss'

import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightDisplayConfig } from '~/queries/nodes/InsightViz/InsightDisplayConfig'
import { DashboardFilter, HogQLQuery, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps, InsightShortId, PropertyFilterType, PropertyOperator } from '~/types'

import { SqlInsightFilters } from './SqlInsightFilters'

const query: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        dateRange: { date_from: '-30d' },
        interval: 'day',
    },
}

const filtersOverride: DashboardFilter = {
    date_from: '-7d',
    interval: 'week',
    compareFilter: { compare: true },
    properties: [
        { key: '$browser', type: PropertyFilterType.Event, operator: PropertyOperator.Exact, value: ['Chrome'] },
    ],
}

const insightProps: InsightLogicProps = {
    dashboardItemId: 'dashboard-filters-example' as InsightShortId,
    dashboardId: 1,
    cachedInsight: { short_id: 'dashboard-filters-example' as InsightShortId, query, saved: true },
    filtersOverride,
    doNotLoad: true,
}

const meta: Meta<{ insightProps: InsightLogicProps }> = {
    title: 'Scenes-App/Insights/Dashboard filter controls',
    args: { insightProps },
    render: ({ insightProps }) => (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className="InsightVizDisplay InsightVizDisplay--type-trends border rounded bg-surface-primary">
                <InsightDisplayConfig />
            </div>
        </BindLogic>
    ),
}
export default meta

type Story = StoryObj<typeof meta>

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
        insightProps: {
            ...insightProps,
            tileFiltersOverride: { date_from: '-14d', interval: 'month', filterTestAccounts: false },
        },
    },
}

export const SavedFilters: Story = {
    args: { insightProps: { ...insightProps, filtersOverride: undefined } },
}

const sqlQuery: HogQLQuery = {
    kind: NodeKind.HogQLQuery,
    query: 'SELECT count() FROM events WHERE {filters}',
    filters: { dateRange: { date_from: '-30d' } },
}

export const SqlFilters: Story = {
    args: { insightProps: { ...insightProps, cachedInsight: { ...insightProps.cachedInsight, query: sqlQuery } } },
    render: ({ insightProps }) => (
        <BindLogic logic={insightLogic} props={insightProps}>
            <SqlInsightFilters query={sqlQuery} setQuery={(): void => {}}>
                <div />
            </SqlInsightFilters>
        </BindLogic>
    ),
}
