import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { StickinessVisualizer } from './StickinessVisualizer'
import type { StickinessQuery, StickinessResult } from './types'

// Stickiness distribution: how many intervals (here, days) users were active in the period.
// `count` is the series total (the denominator for the percentage Y-axis); `data` are the raw
// per-bucket actor counts the visualizer converts to a share of `count`.
const DAYS = ['1', '2', '3', '4', '5', '6', '7']
const LABELS = ['1 day', '2 days', '3 days', '4 days', '5 days', '6 days', '7 days']

const RESULTS: StickinessResult = [
    { label: 'Pageview', count: 1000, data: [620, 180, 90, 50, 30, 18, 12], days: DAYS, labels: LABELS },
]

const MULTI_SERIES: StickinessResult = [
    { label: 'Pageview', count: 1000, data: [620, 180, 90, 50, 30, 18, 12], days: DAYS, labels: LABELS },
    { label: 'Autocapture', count: 400, data: [300, 60, 20, 10, 5, 3, 2], days: DAYS, labels: LABELS },
]

const stickinessQuery: StickinessQuery = { kind: 'StickinessQuery', interval: 'day' }

// The visualizer sizes its canvas off a ResizeObserver, so give it a definite width — a `w-full` box
// can measure 0 at mount in the headless snapshot runner and paint nothing.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Stickiness',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => <StickinessVisualizer query={stickinessQuery} results={RESULTS} />,
    name: 'Single series',
}

export const MultipleSeries: Story = {
    render: () => <StickinessVisualizer query={stickinessQuery} results={MULTI_SERIES} />,
    name: 'Multiple series',
}
