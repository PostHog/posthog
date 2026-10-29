import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'
import { useChartTheme } from '@posthog/quill-charts'

import { sqlEvidenceChart } from './sqlEvidenceChart'
import { StoryEvidenceChart } from './StoryEvidenceChart'

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

const HOURS = [
    '2026-10-26 21:00:00',
    '2026-10-26 22:00:00',
    '2026-10-26 23:00:00',
    '2026-10-27 00:00:00',
    '2026-10-27 01:00:00',
]

function LineChart(): ReactElement {
    const rows = HOURS.flatMap((hour, index) => [
        [hour, 'EU', [0.91, 0.9, 0.55, 0.62, 0.7][index]],
        ...(index === 2 ? [] : [[hour, 'US', [0.88, 0.89, 0.52, 0.6, 0.69][index]]]),
    ])
    return (
        <StoryEvidenceChart
            className="h-[260px]"
            theme={useChartTheme()}
            chart={sqlEvidenceChart(['hour', 'region', 'hit_rate'], rows)!}
        />
    )
}

export const Line: Story = {
    render: () => <LineChart />,
}
