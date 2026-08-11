import type { Meta, StoryObj } from '@storybook/react'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { LinkedReportsSection } from './LinkedReports'

// The right pane's self-driving section, above the exception card. Whether a fix exists is what a
// person triaging needs, so the states worth a snapshot are a proposed fix, a merged fix, and a report
// with no pull request to point at yet.

const meta: Meta<typeof LinkedReportsSection> = {
    title: 'Scenes-App/ErrorTracking/LinkedReports',
    component: LinkedReportsSection,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-08-10' },
}
export default meta

type Story = StoryObj<typeof LinkedReportsSection>

function makeReport(overrides: Partial<SignalReportApi> = {}): SignalReportApi {
    return {
        id: '019f9582-93e7-77c1-8912-4f541d70cb13',
        status: 'ready',
        title: 'fix(replay): guard against a missing snapshot index',
        summary:
            'The player throws when a recording ends on a snapshot the index never received.\n\n## Problem\n\nThe index is built once per load.',
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64772',
        implementation_pr_merged: false,
        updated_at: '2026-08-09T21:00:00Z',
        ...overrides,
    } as SignalReportApi
}

/**
 * A width harness only. The section in its real pane, next to the exception card, is covered by the
 * `Scenes-App/ErrorTracking` story "Issue scene with self-driving".
 */
function Pane({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="w-[700px]">{children}</div>
}

export const FixProposed: Story = {
    render: () => (
        <Pane>
            <LinkedReportsSection reports={[makeReport()]} />
        </Pane>
    ),
}

export const SeveralReportsAcrossStates: Story = {
    render: () => (
        <Pane>
            <LinkedReportsSection
                reports={[
                    makeReport(),
                    makeReport({
                        id: '019f954a-8ed0-7a18-a198-3ffed1a2def0',
                        status: 'resolved',
                        title: 'fix(replay): stop dropping events after a tab regains focus',
                        summary: 'Events queued while the tab was hidden are discarded when it regains focus.',
                        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64773',
                        implementation_pr_merged: true,
                        updated_at: '2026-08-09T18:30:00Z',
                    }),
                    makeReport({
                        id: '019f9569-5d45-780a-8b63-ecd0dc71148e',
                        status: 'in_progress',
                        title: null,
                        summary: 'Needs a product call on whether the player should re-key on recording change.',
                        implementation_pr_url: null,
                        updated_at: '2026-08-09T12:00:00Z',
                    }),
                ]}
            />
        </Pane>
    ),
}

/** The narrowest the pane gets, where the title and the fix state compete for width. */
export const NarrowPane: Story = {
    render: () => (
        <div className="w-[375px]">
            <LinkedReportsSection reports={[makeReport()]} />
        </div>
    ),
}
