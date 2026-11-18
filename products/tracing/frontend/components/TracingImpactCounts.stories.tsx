import type { Meta, StoryObj } from '@storybook/react'

import type { _TracingImpactResponseApi } from 'products/tracing/frontend/generated/api.schemas'

import { TracingImpactCounts } from './TracingImpactCounts'

const meta: Meta<typeof TracingImpactCounts> = {
    title: 'Scenes-App/Tracing/TracingImpactCounts',
    component: TracingImpactCounts,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof TracingImpactCounts>

function makeImpact(overrides: Partial<_TracingImpactResponseApi> = {}): _TracingImpactResponseApi {
    return {
        total: 12400,
        spansWithSessionId: 11800,
        sessions: 214,
        spansWithDistinctId: 9600,
        users: 96,
        topSessions: [
            { value: '01936d3a-5983-7e70-b287-2f21ab1a70c1', count: 3200 },
            { value: '01936d3a-72aa-7c3e-8f10-4a5f0d9be2d4', count: 1900 },
            { value: '01936d3a-9c41-7b52-a6e3-1d8c27f4e0b9', count: 450 },
        ],
        topUsers: [
            { value: 'user-482@example.com', count: 4100 },
            { value: 'user-191@example.com', count: 2600 },
        ],
        ...overrides,
    }
}

export const SessionsAndUsers: Story = {
    args: { impact: makeImpact() },
}

/** Spans that carry a session ID but were never linked to a person. */
export const SessionsOnly: Story = {
    args: { impact: makeImpact({ spansWithDistinctId: 0, users: 0 }) },
}

/** Partial instrumentation: the tooltip is what tells the reader the count covers a slice. */
export const PartialCoverage: Story = {
    args: { impact: makeImpact({ spansWithSessionId: 380, sessions: 12, spansWithDistinctId: 0, users: 0 }) },
}

/** Server-only spans with no identity attributes at all. */
export const NoCoverage: Story = {
    args: { impact: makeImpact({ spansWithSessionId: 0, sessions: 0, spansWithDistinctId: 0, users: 0 }) },
}
