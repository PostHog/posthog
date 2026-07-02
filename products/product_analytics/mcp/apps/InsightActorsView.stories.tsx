import type { Meta, StoryObj } from '@storybook/react'

import { McpThemeDecorator } from '@posthog/mcp-ui/storybook/decorator'

import { InsightActorsView, type InsightActorsData } from './InsightActorsView'

const meta: Meta = {
    title: 'MCP Apps/Insight Actors',
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

const openLink = (url: string): void => {
    window.open(url, '_blank')
}

// `results` is the flattened actors table: `[distinct_id, email, name, event_count]`, plus a
// `recordings` column (string[] of replay URLs) when the source requested matched recordings.
const withEventCounts: InsightActorsData = {
    query: { kind: 'ActorsQuery', source: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } } },
    results: {
        columns: ['distinct_id', 'email', 'name', 'event_count'],
        results: [
            ['0a1b2c3d', 'alice@example.com', 'Alice Adams', 128],
            ['1c2d3e4f', 'ben@example.com', 'Ben Brown', 73],
            ['2e3f4a5b', null, null, 51],
            ['3f4a5b6c', 'cara@example.com', 'Cara Cohen', 22],
            ['4a5b6c7d', null, null, 9],
        ],
    },
    hasMore: false,
    offset: 0,
}

const withRecordings: InsightActorsData = {
    query: { kind: 'ActorsQuery', source: { kind: 'InsightActorsQuery', source: { kind: 'TrendsQuery' } } },
    results: {
        columns: ['distinct_id', 'email', 'name', 'event_count', 'recordings'],
        results: [
            [
                '0a1b2c3d',
                'alice@example.com',
                'Alice Adams',
                128,
                ['https://us.posthog.com/replay/aaa', 'https://us.posthog.com/replay/bbb'],
            ],
            ['1c2d3e4f', 'ben@example.com', 'Ben Brown', 73, ['https://us.posthog.com/replay/ccc']],
            ['2e3f4a5b', null, null, 51, []],
        ],
    },
    hasMore: true,
    offset: 0,
}

// Membership-based sources (stickiness, lifecycle) project only the actor — no event count and no
// recordings — so the table collapses to just the Actor column with no default sort.
const membershipOnly: InsightActorsData = {
    query: { kind: 'ActorsQuery', source: { kind: 'InsightActorsQuery', source: { kind: 'StickinessQuery' } } },
    results: {
        columns: ['distinct_id', 'email', 'name'],
        results: [
            ['0a1b2c3d', 'alice@example.com', 'Alice Adams'],
            ['1c2d3e4f', 'ben@example.com', 'Ben Brown'],
            ['2e3f4a5b', null, null],
        ],
    },
    hasMore: false,
    offset: 0,
}

export const EventCounts: Story = {
    render: () => <InsightActorsView data={withEventCounts} openLink={openLink} />,
    name: 'Event counts',
}

export const MembershipOnly: Story = {
    render: () => <InsightActorsView data={membershipOnly} openLink={openLink} />,
    name: 'Membership only (stickiness/lifecycle)',
}

export const WithRecordings: Story = {
    render: () => <InsightActorsView data={withRecordings} openLink={openLink} />,
    name: 'With recordings',
}
