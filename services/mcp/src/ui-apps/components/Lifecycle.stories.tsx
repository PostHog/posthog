import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { LifecycleVisualizer } from './LifecycleVisualizer'
import type { LifecycleQuery, LifecycleResult } from './types'

const DAYS = ['2025-06-01', '2025-06-02', '2025-06-03', '2025-06-04', '2025-06-05', '2025-06-06', '2025-06-07']

// `dormant` values come back negated from the backend so a diverging stack lays them below zero.
const RESULTS: LifecycleResult = [
    { status: 'new', label: 'Pageview - new', data: [40, 35, 50, 45, 60, 55, 70], days: DAYS },
    { status: 'returning', label: 'Pageview - returning', data: [20, 30, 35, 40, 45, 50, 55], days: DAYS },
    { status: 'resurrecting', label: 'Pageview - resurrecting', data: [10, 8, 12, 9, 14, 11, 16], days: DAYS },
    { status: 'dormant', label: 'Pageview - dormant', data: [-15, -20, -18, -25, -22, -30, -28], days: DAYS },
]

const lifecycleQuery = (stacked: boolean): LifecycleQuery => ({
    kind: 'LifecycleQuery',
    lifecycleFilter: { stacked },
})

// The visualizer sizes its canvas off a ResizeObserver, so give it a definite width — a `w-full` box
// can measure 0 at mount in the headless snapshot runner and paint nothing.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Lifecycle',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

export const Stacked: Story = {
    render: () => <LifecycleVisualizer query={lifecycleQuery(true)} results={RESULTS} />,
    name: 'Stacked',
}

export const Grouped: Story = {
    render: () => <LifecycleVisualizer query={lifecycleQuery(false)} results={RESULTS} />,
    name: 'Grouped',
}
