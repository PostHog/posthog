import type { Meta, StoryObj } from '@storybook/react'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { LinkedReportsList } from './LinkedReports'

// What the issue page shows above the exception once self-driving has looked at the error. This is the
// entry the ticket thread uses, so the states worth a snapshot are the same ones: a proposed fix, a
// merged fix, and a report with no pull request to point at yet.

const meta: Meta<typeof LinkedReportsList> = {
    title: 'Scenes-App/ErrorTracking/LinkedReports',
    component: LinkedReportsList,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-08-10' },
}
export default meta

type Story = StoryObj<typeof LinkedReportsList>

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

/** The right-hand column is 375px at its narrowest and about 700px at the default split. */
function Column({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="w-[700px]">{children}</div>
}

export const FixProposed: Story = {
    render: () => (
        <Column>
            <LinkedReportsList reports={[makeReport()]} />
        </Column>
    ),
}

export const SeveralReportsAcrossStates: Story = {
    render: () => (
        <Column>
            <LinkedReportsList
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
        </Column>
    ),
}

/** The narrowest the column gets, where the title and the fix state compete for width. */
export const NarrowColumn: Story = {
    render: () => (
        <div className="w-[375px]">
            <LinkedReportsList reports={[makeReport()]} />
        </div>
    ),
}
