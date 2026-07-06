import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { TrendsVisualizer } from './TrendsVisualizer'
import type { ChartDisplayType, TrendsQuery, TrendsResult } from './types'

const DAYS = ['2025-05-26', '2025-05-27', '2025-05-28', '2025-05-29', '2025-05-30', '2025-05-31', '2025-06-01']

const trendsQuery = (display: ChartDisplayType): TrendsQuery => ({ kind: 'TrendsQuery', trendsFilter: { display } })

// The visualizer sizes its canvas off a ResizeObserver, so give it a definite width — a `w-full` box
// can measure 0 at mount in the headless snapshot runner and paint nothing.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Trends',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const renderTrends = (query: TrendsQuery, results: TrendsResult): ReactElement => (
    <TrendsVisualizer query={query} results={results} />
)

export const SingleSeries: Story = {
    render: () =>
        renderTrends(trendsQuery('ActionsLineGraph'), [
            { label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
        ]),
    name: 'Single series',
}

export const MultiSeries: Story = {
    render: () =>
        renderTrends(trendsQuery('ActionsLineGraph'), [
            { label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
            { label: 'Signups', data: [42, 38, 51, 49, 63, 58, 72], days: DAYS },
            { label: 'Purchases', data: [8, 12, 9, 15, 11, 18, 14], days: DAYS },
        ]),
    name: 'Multi-series',
}

export const AreaChart: Story = {
    render: () =>
        renderTrends(trendsQuery('ActionsAreaGraph'), [
            { label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
            { label: 'Signups', data: [42, 38, 51, 49, 63, 58, 72], days: DAYS },
        ]),
    name: 'Area chart',
}

export const TimeSeriesBar: Story = {
    render: () =>
        renderTrends(trendsQuery('ActionsBar'), [
            { label: 'Pageviews', data: [420, 380, 510, 490, 630, 580, 720], days: DAYS },
            { label: 'Signups', data: [42, 38, 51, 49, 63, 58, 72], days: DAYS },
        ]),
    name: 'Time-series bar',
}

export const BarValueFewSeries: Story = {
    render: () =>
        renderTrends(trendsQuery('ActionsBarValue'), [
            { label: 'Chrome', aggregated_value: 8421 },
            { label: 'Firefox', aggregated_value: 3204 },
            { label: 'Safari', aggregated_value: 2817 },
        ]),
    name: 'Bar value — few series',
}

export const BarValueManyBreakdowns: Story = {
    render: () =>
        renderTrends(trendsQuery('ActionsBarValue'), [
            { label: 'United States', aggregated_value: 14320 },
            { label: 'United Kingdom', aggregated_value: 6210 },
            { label: 'Germany', aggregated_value: 4890 },
            { label: 'France', aggregated_value: 3720 },
            { label: 'Canada', aggregated_value: 2940 },
            { label: 'Australia', aggregated_value: 2310 },
            { label: 'Netherlands', aggregated_value: 1870 },
            { label: 'India', aggregated_value: 1640 },
        ]),
    name: 'Bar value — many breakdowns',
}
