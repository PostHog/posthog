import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsSlopeGraph from '~/mocks/fixtures/api/projects/team_id/insights/trendsSlopeGraph.json'

import { TrendsSlopeChart } from './TrendsSlopeChart'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/TrendsSlopeChart',
    component: TrendsSlopeChart,
    parameters: {
        layout: 'centered',
        mockDate: '2022-04-01',
        featureFlags: [FEATURE_FLAGS.SLOPE_GRAPH_INSIGHT],
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '[data-attr=trends-slope-graph] canvas',
        },
    },
}
export default meta

const slopeInsight = __trendsSlopeGraph as any

export const Default: Story = {
    render: () => <InsightVizStory insight={slopeInsight} />,
}

// With the "Show legend" toggle on, the slope chart shows its own legend with each series'
// first-to-last change — there's only ever the one legend.
const slopeInsightWithLegend = {
    ...slopeInsight,
    query: {
        ...slopeInsight.query,
        source: {
            ...slopeInsight.query.source,
            trendsFilter: { ...slopeInsight.query.source.trendsFilter, showLegend: true },
        },
    },
}

export const WithLegend: Story = {
    render: () => <InsightVizStory insight={slopeInsightWithLegend} />,
}

// The backend flags the last bucket as the current incomplete period (`incomplete_end`), so the
// second half of the connector to the end point is dashed — the same affordance the line chart uses.
const slopeInsightIncompletePeriod = {
    ...slopeInsight,
    result: slopeInsight.result.map((series: Record<string, unknown>) => ({ ...series, incomplete_end: true })),
}

export const IncompletePeriod: Story = {
    render: () => <InsightVizStory insight={slopeInsightIncompletePeriod} />,
}
