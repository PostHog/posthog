import type { Meta, StoryObj } from '@storybook/react'

import type { _LogsImpactResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { LogsImpactCounts } from './LogsImpactCounts'

// The counts sit in the display bar beside "N logs". The states worth a snapshot are the ones
// that read differently to someone scanning the bar: both IDs present, only one of them, and a
// project whose logs carry neither.

const meta: Meta<typeof LogsImpactCounts> = {
    title: 'Scenes-App/Logs/LogsImpactCounts',
    component: LogsImpactCounts,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof LogsImpactCounts>

function makeImpact(overrides: Partial<_LogsImpactResponseApi> = {}): _LogsImpactResponseApi {
    return {
        total: 12400,
        logsWithSessionId: 11800,
        sessions: 214,
        logsWithDistinctId: 9600,
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
        sessionGroupKey: { source: 'log', key: 'sessionId' },
        ...overrides,
    }
}

export const SessionsAndUsers: Story = {
    args: { impact: makeImpact() },
}

/** Server logs that carry a session ID but were never linked to a person. */
export const SessionsOnly: Story = {
    args: { impact: makeImpact({ logsWithDistinctId: 0, users: 0 }) },
}

/** Partial instrumentation: the tooltip is what tells the reader the count covers a slice. */
export const PartialCoverage: Story = {
    args: { impact: makeImpact({ logsWithSessionId: 380, sessions: 12, logsWithDistinctId: 0, users: 0 }) },
}

/** Infrastructure logs with no identity attributes at all. */
export const NoCoverage: Story = {
    args: { impact: makeImpact({ logsWithSessionId: 0, sessions: 0, logsWithDistinctId: 0, users: 0 }) },
}
