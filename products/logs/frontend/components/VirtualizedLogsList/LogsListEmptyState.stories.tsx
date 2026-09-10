import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { LogsRetentionWindow } from 'products/logs/frontend/logsRetentionWindow'

import { LogsListEmptyState } from './LogsListEmptyState'

// The states worth a snapshot are the three a reader has to tell apart: a search that genuinely
// matched nothing, a range that sits entirely outside retention, and one that only partly does.

const meta: Meta<typeof LogsListEmptyState> = {
    title: 'Scenes-App/Logs/LogsListEmptyState',
    component: LogsListEmptyState,
    args: { retentionRulesAvailable: true },
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof LogsListEmptyState>

const retentionWindow = (coversWholeRange: boolean): LogsRetentionWindow => ({
    retentionDays: 14,
    start: dayjs('2026-08-27T00:00:00Z'),
    coversWholeRange,
})

export const NoLogsFound: Story = {
    args: { onExpandTimeRange: () => {} },
}

/** The customer's case: retention was raised, but the older days were already dropped. */
export const RangeOlderThanRetention: Story = {
    args: { retention: retentionWindow(true), onSearchRetainedRange: () => {} },
}

export const RangePartlyOlderThanRetention: Story = {
    args: { retention: retentionWindow(false), onSearchRetainedRange: () => {} },
}
