import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { EvidenceInlineChart } from './EvidenceInlineChart'

// The chart measures its box with a ResizeObserver, so give it a definite width.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Explain Chart/Evidence chart',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: { testOptions: { skipDarkMode: true } },
}
export default meta

type Story = StoryObj<{}>

export const Line: Story = {
    render: () => (
        <EvidenceInlineChart
            className="h-[260px]"
            chart={{
                type: 'line',
                labels: [
                    'Oct 26 18:00',
                    'Oct 26 19:00',
                    'Oct 26 20:00',
                    'Oct 26 21:00',
                    'Oct 26 22:00',
                    'Oct 26 23:00',
                ],
                series: [
                    { name: 'EU hit rate', values: [0.91, 0.9, 0.55, 0.62, 0.7, 0.78] },
                    { name: 'US hit rate', values: [0.88, 0.89, 0.52, 0.6, 0.69, 0.8] },
                ],
            }}
        />
    ),
}
