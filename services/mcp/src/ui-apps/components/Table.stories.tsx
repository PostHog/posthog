import type { Meta, StoryFn, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { TableVisualizer } from './TableVisualizer'
import type { HogQLResult } from './types'

// A timestamp column plus a numeric column triggers the time-series detection path,
// which renders a chart instead of a table — the shape execute-sql results most often take.
const TIME_SERIES: HogQLResult = {
    columns: ['day', 'unique_users'],
    results: [
        ['2025-05-26T00:00:00', 1450],
        ['2025-05-27T00:00:00', 1620],
        ['2025-05-28T00:00:00', 1390],
        ['2025-05-29T00:00:00', 1810],
        ['2025-05-30T00:00:00', 2050],
        ['2025-05-31T00:00:00', 980],
        ['2025-06-01T00:00:00', 1240],
    ],
}

// 1 row × 1 numeric column triggers the big-number path.
const SINGLE_NUMBER: HogQLResult = {
    columns: ['total_events'],
    results: [[1_284_942]],
}

// Mixed column types fall through to the plain table, exercising per-type cell
// formatting (numbers, booleans, nulls, nested objects).
const TABLE: HogQLResult = {
    columns: ['event', 'count', 'is_internal', 'last_seen', 'properties'],
    results: [
        ['$pageview', 48210, false, '2025-06-01T12:34:56', { $browser: 'Chrome' }],
        ['$autocapture', 21984, false, '2025-06-01T11:20:03', null],
        ['sign_up', 312, true, '2025-05-31T09:12:44', { plan: 'free' }],
    ],
}

// The visualizer sizes its canvas off a ResizeObserver, so give it a definite width — a `w-full` box
// can measure 0 at mount in the headless snapshot runner and paint nothing.
const FixedWidth = (Story: StoryFn): ReactElement => (
    <div className="w-[680px]">
        <Story />
    </div>
)

const meta: Meta = {
    title: 'MCP Apps/Query results',
    decorators: [McpThemeDecorator, FixedWidth],
    parameters: {
        testOptions: {
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

export const TimeSeries: Story = {
    render: () => <TableVisualizer results={TIME_SERIES} />,
    name: 'Time series',
}

export const SingleNumber: Story = {
    render: () => <TableVisualizer results={SINGLE_NUMBER} />,
    name: 'Single number',
}

export const Table: Story = {
    render: () => <TableVisualizer results={TABLE} />,
}
