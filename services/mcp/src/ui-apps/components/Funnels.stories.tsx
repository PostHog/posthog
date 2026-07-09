import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { FunnelVisualizer } from './FunnelVisualizer'
import type { FunnelResult, FunnelsQuery } from './types'

const FUNNELS_QUERY: FunnelsQuery = { kind: 'FunnelsQuery' }

// The visualizer sizes its canvas off a ResizeObserver, so give it a definite width — a `w-full` box
// can measure 0 at mount in the headless snapshot runner and paint nothing.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Funnels',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

const renderFunnel = (results: FunnelResult): ReactElement => (
    <FunnelVisualizer query={FUNNELS_QUERY} results={results} />
)

export const ThreeStep: Story = {
    render: () =>
        renderFunnel([
            { name: 'Pageview', count: 1000, order: 0 },
            { name: 'Signed up', count: 420, order: 1 },
            { name: 'Activated', count: 180, order: 2 },
        ]),
    name: 'Three-step funnel',
}

export const SteepDropoff: Story = {
    render: () =>
        renderFunnel([
            { name: 'Visited', count: 5000, order: 0 },
            { name: 'Added to cart', count: 800, order: 1 },
            { name: 'Checkout started', count: 240, order: 2 },
            { name: 'Purchased', count: 96, order: 3 },
        ]),
    name: 'Steep drop-off',
}

// Steps that share an event name must still render one bar each. The band scale dedupes its domain,
// so positioning by name would collapse both `$pageview` steps onto a single slot — this guards the
// index-keyed band + tick formatter that keeps them distinct.
export const DuplicateStepNames: Story = {
    render: () =>
        renderFunnel([
            { name: '$pageview', count: 10, order: 0 },
            { name: '$pageview', count: 2, order: 1 },
        ]),
    name: 'Duplicate step names',
}
