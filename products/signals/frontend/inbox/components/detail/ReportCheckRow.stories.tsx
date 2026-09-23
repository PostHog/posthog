import type { Meta, StoryObj } from '@storybook/react'

import { IconTarget } from '@posthog/icons'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { DetailSection } from './DetailSection'
import { buildReportCheckRows, reportChecksMeta } from './reportCheckPresentation'
import { ReportCheckRow } from './ReportCheckRow'

function check(overrides: Partial<SignalReportCheckApi>): SignalReportCheckApi {
    return {
        id: 'check',
        title: 'Checkout errors stay at zero after the retry fix',
        rationale: 'The retry fix should stop the exception reaching the customer.',
        kind: 'agent',
        status: 'active',
        config: { instructions: 'Re-read the issue.', skill_name: 'signals-scout-error-tracking', probe_hints: [] },
        next_run_at: '2026-09-27T09:00:00Z',
        soak_minutes: 10080,
        run_interval_minutes: null,
        runs_remaining: 1,
        expires_at: '2026-10-27T09:00:00Z',
        last_run_at: null,
        last_outcome: null,
        dispatched_at: null,
        consecutive_errors: 0,
        created_at: '2026-09-20T09:00:00Z',
        updated_at: '2026-09-20T09:00:00Z',
        ...overrides,
    } as SignalReportCheckApi
}

const everyState: SignalReportCheckApi[] = [
    check({ id: 'scheduled' }),
    check({
        id: 'waiting',
        status: 'pending',
        title: 'No new reports of the export timeout',
        kind: 'metric_threshold',
        config: { comparison: { operator: 'lte', value: 0 } },
        soak_minutes: 4320,
    }),
    check({
        id: 'passed',
        status: 'passed',
        kind: 'metric_threshold',
        config: { comparison: { operator: 'lte', value: 20 } },
        title: 'Signup form rageclicks fall to at most 20 per 14 days',
        last_run_at: '2026-09-20T09:00:00Z',
    }),
    check({
        id: 'failed',
        status: 'failed',
        title: 'The export backlog stays clear',
        last_run_at: '2026-09-27T09:00:00Z',
    }),
    check({
        id: 'expired',
        status: 'expired',
        title: 'Confirm the retry budget holds',
        updated_at: '2026-10-27T09:00:00Z',
    }),
    check({
        id: 'cancelled',
        status: 'cancelled',
        title: 'Replaced when research re-ran on this report',
        updated_at: '2026-09-21T09:00:00Z',
    }),
]

const explanations = new Map([
    ['passed', '11 rageclicks in the last 14 days. Expected at most 20, was 64 when set.'],
    ['failed', '14 new events after the fix, on the same stack frame.'],
])

function ChecksSection({ checks }: { checks: SignalReportCheckApi[] }): JSX.Element {
    return (
        <DetailSection
            icon={<IconTarget />}
            title="Follow-up checks"
            meta={<span className="text-xs text-tertiary tabular-nums">{reportChecksMeta(checks)}</span>}
        >
            <div className="flex flex-col gap-1.5">
                {buildReportCheckRows(checks, explanations).map((row) => (
                    <ReportCheckRow key={row.check.id} row={row} cancelling={false} onCancel={() => undefined} />
                ))}
            </div>
        </DetailSection>
    )
}

const meta: Meta<typeof ChecksSection> = {
    title: 'Scenes-App/Inbox/Detail/Follow-up checks',
    component: ChecksSection,
    parameters: { layout: 'centered', viewMode: 'story' },
    decorators: [
        (Story, context) => (
            // The rail is 26rem wide, and about 20rem of it survives next to an open side panel.
            <div
                className={`${context.parameters.railWidth === 'narrow' ? 'w-[20rem]' : 'w-[26rem]'} max-w-[calc(100vw-2rem)] rounded border bg-primary p-4`}
            >
                <Story />
            </div>
        ),
    ],
}

export default meta

type Story = StoryObj<typeof ChecksSection>

export const EveryState: Story = {
    args: { checks: everyState },
}

export const Running: Story = {
    args: { checks: [check({ id: 'running', dispatched_at: '2026-09-21T09:00:00Z' })] },
}

export const NarrowRail: Story = {
    parameters: { railWidth: 'narrow' },
    args: { checks: everyState },
}
