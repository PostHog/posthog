import { MOCK_DEFAULT_USER } from '~/lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const TOPICS = [
    {
        topic_id: 't1',
        label: 'Build and tune SQL insights',
        summary: 'Agents write and refine SQL for charts.',
        x: 0.9,
        y: 0.2,
        calls: 5200,
        share_pct: 46.0,
    },
    {
        topic_id: 't2',
        label: 'Investigate error spikes',
        summary: 'Agents look for failing calls.',
        x: -0.6,
        y: 0.7,
        calls: 2900,
        share_pct: 25.7,
    },
    {
        topic_id: 't3',
        label: 'Review session replays',
        summary: 'Agents find recordings to watch.',
        x: -0.4,
        y: -0.8,
        calls: 2100,
        share_pct: 18.6,
    },
    {
        topic_id: 't4',
        label: 'Manage feature flags',
        summary: 'Agents list and edit flags.',
        x: 0.5,
        y: -0.6,
        calls: 1100,
        share_pct: 9.7,
    },
]

function pointsAround(topic: (typeof TOPICS)[number], count: number, seed: number): any[] {
    const points = []
    for (let i = 0; i < count; i++) {
        const angle = ((i * 137.5 + seed) * Math.PI) / 180
        const radius = 0.05 + (0.25 * ((i * 7 + seed) % 10)) / 10
        points.push({
            intent_hash: `${topic.topic_id}-${i}`,
            intent_text: `${topic.label}: example intent ${i + 1}`,
            x: topic.x + radius * Math.cos(angle),
            y: topic.y + radius * Math.sin(angle),
            topic_id: topic.topic_id,
            is_outlier: i % 9 === 8,
            calls: 40 - i,
            tool: 'warehouse/execute-sql',
        })
    }
    return points
}

const POINTS = TOPICS.flatMap((topic, index) => pointsAround(topic, 18, index * 31))
// The mocked query endpoint fails for this tool, so a story can show the error screen.
const FAILING_TOOL = 'tool-with-a-failing-query'

const meta: Meta = {
    title: 'Scenes-App/MCP Analytics/Intent map',
    component: App,
    decorators: [
        (Story, context) =>
            mswDecorator({
                get: { '/api/users/@me/': { ...MOCK_DEFAULT_USER, theme_mode: context.globals.theme ?? 'light' } },
            })(Story, context),
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': async ({ request }) => {
                    const body = (await request.json()) as {
                        query?: { kind?: string; topicId?: string; toolName?: string }
                    }
                    if (body?.query?.kind !== 'MCPIntentMapQuery') {
                        return [200, { results: [] }]
                    }
                    if (body.query.toolName === FAILING_TOOL) {
                        return [500, { detail: 'Query timed out' }]
                    }
                    const topicId = body.query.topicId
                    const points = topicId ? POINTS.filter((p) => p.topic_id === topicId) : POINTS
                    const topics = topicId ? TOPICS.filter((t) => t.topic_id === topicId) : TOPICS
                    return [200, { results: points, topics, total_points: points.length }]
                },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-07T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.MCP_ANALYTICS_INTENT_TOPICS],
    },
}
export default meta

type Story = StoryObj<{}>

export const IntentMap: Story = {
    parameters: { pageUrl: urls.mcpAnalyticsIntentMap(), testOptions: { viewportWidths: ['medium', 'wide'] } },
}

export const IntentMapOneTopic: Story = {
    parameters: { pageUrl: urls.mcpAnalyticsIntentMap({ topic: 't1' }), testOptions: { viewportWidths: ['wide'] } },
}

export const IntentMapFlagOff: Story = {
    parameters: { pageUrl: urls.mcpAnalyticsIntentMap(), featureFlags: [] },
}

export const IntentMapLoadFailed: Story = {
    parameters: { pageUrl: urls.mcpAnalyticsIntentMap({ tool: FAILING_TOOL }) },
}
