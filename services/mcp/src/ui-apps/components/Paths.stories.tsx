import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { PathsVisualizer } from './PathsVisualizer'
import type { PathsResult } from './types'

// The visualizer sizes its canvas off a ResizeObserver, so give it a definite width — a `w-full` box
// can measure 0 at mount in the headless snapshot runner and paint nothing.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Paths',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const STORE_PATHS: PathsResult = [
    {
        source: '1_https://example.com/',
        target: '2_https://example.com/product',
        value: 3705,
        average_conversion_time: 42000,
    },
    {
        source: '1_https://example.com/',
        target: '2_https://example.com/cart',
        value: 1240,
        average_conversion_time: 18000,
    },
    {
        source: '1_https://example.com/',
        target: '2_https://example.com/checkout',
        value: 303,
        average_conversion_time: 9000,
    },
    {
        source: '2_https://example.com/product',
        target: '3_https://example.com/cart',
        value: 1596,
        average_conversion_time: 65000,
    },
    {
        source: '2_https://example.com/product',
        target: '3_https://example.com/',
        value: 555,
        average_conversion_time: 31000,
    },
    {
        source: '2_https://example.com/product',
        target: '3_https://example.com/product',
        value: 490,
        average_conversion_time: 22000,
    },
    {
        source: '2_https://example.com/cart',
        target: '3_https://example.com/checkout',
        value: 842,
        average_conversion_time: 12000,
    },
    {
        source: '2_https://example.com/cart',
        target: '3_https://example.com/product',
        value: 210,
        average_conversion_time: 47000,
    },
    {
        source: '3_https://example.com/cart',
        target: '4_https://example.com/checkout',
        value: 902,
        average_conversion_time: 15000,
    },
    {
        source: '3_https://example.com/',
        target: '4_https://example.com/product',
        value: 320,
        average_conversion_time: 28000,
    },
]

export const StoreJourneys: Story = {
    render: () => <PathsVisualizer results={STORE_PATHS} />,
    name: 'Store page journeys',
}

export const SingleTransition: Story = {
    render: () => (
        <PathsVisualizer
            results={[{ source: '1_app opened', target: '2_report viewed', value: 120, average_conversion_time: 3500 }]}
        />
    ),
    name: 'Single transition',
}

export const Empty: Story = {
    render: () => <PathsVisualizer results={[]} />,
    name: 'No path data',
}
