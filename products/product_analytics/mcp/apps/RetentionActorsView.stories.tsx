import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { type InsightActorsData } from './insightActorsTransforms'
import { RetentionActorsView } from './RetentionActorsView'

const meta: Meta = {
    title: 'MCP Apps/Retention Actors',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // McpThemeDecorator has no dark mode, so skip it to avoid duplicated snapshots.
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

// `results` is the flattened actors table: `[distinct_id, email, name, <period>_0 … <period>_N]`,
// where each interval cell is 1 (returned) or 0 (did not).
const dailyCohort: InsightActorsData = {
    query: {
        kind: 'ActorsQuery',
        source: {
            kind: 'InsightActorsQuery',
            interval: 0,
            source: { kind: 'RetentionQuery', retentionFilter: { period: 'Day', totalIntervals: 8 } },
        },
    },
    results: {
        columns: [
            'distinct_id',
            'email',
            'name',
            'day_0',
            'day_1',
            'day_2',
            'day_3',
            'day_4',
            'day_5',
            'day_6',
            'day_7',
        ],
        results: [
            ['0a1b2c3d', 'alice@example.com', 'Alice Adams', 1, 1, 1, 1, 1, 0, 1, 0],
            ['1c2d3e4f', 'ben@example.com', 'Ben Brown', 1, 1, 1, 0, 1, 0, 0, 0],
            ['2e3f4a5b', 'cara@example.com', 'Cara Cohen', 1, 1, 0, 1, 0, 0, 0, 0],
            ['3f4a5b6c', null, null, 1, 1, 0, 0, 0, 0, 0, 0],
            ['4a5b6c7d', 'dan@example.com', 'Dan Diaz', 1, 0, 1, 0, 0, 0, 0, 0],
            ['5b6c7d8e', 'erin@example.com', null, 1, 0, 0, 0, 0, 0, 0, 0],
            ['6c7d8e9f', null, null, 1, 0, 0, 0, 0, 0, 0, 0],
        ],
    },
    hasMore: false,
    offset: 0,
}

export const Daily: Story = {
    render: () => <RetentionActorsView data={dailyCohort} />,
    name: 'Daily cohort',
}
