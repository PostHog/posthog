import type { Meta, StoryObj } from '@storybook/react'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'

import { SuggestionBanner } from './SuggestionBanner'

const meta: Meta<typeof SuggestionBanner> = {
    title: 'Scenes-App/Insights/PostHog AI suggestion',
    component: SuggestionBanner,
}
export default meta

type Story = StoryObj<typeof SuggestionBanner>

const PREVIOUS_QUERY: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        dateRange: { date_from: '-7d' },
        interval: 'day',
    },
}

const SUGGESTED_QUERY: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: 'sign up' }],
        dateRange: { date_from: '-30d' },
        interval: 'week',
        breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
    },
}

// The editor panel is the narrowest surface this renders on, so the story pins that width.
export const Default: Story = {
    render: () => (
        <div className="w-[420px]">
            <SuggestionBanner
                previousQuery={PREVIOUS_QUERY}
                suggestedQuery={SUGGESTED_QUERY}
                onKeep={() => {}}
                onReject={() => {}}
            />
        </div>
    ),
}
