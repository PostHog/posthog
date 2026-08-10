import type { Meta, StoryObj } from '@storybook/react'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { LinkedReportsIndicatorDisplay } from './LinkedReportsIndicator'

// What the issue header shows once self-driving has looked at the error. Whether a fix exists is the
// whole point of the chip, so one story carries the PR states next to the status that stands in
// without one, and the collapsed form for an issue that grouped into several reports.

const meta: Meta<typeof LinkedReportsIndicatorDisplay> = {
    title: 'Scenes-App/ErrorTracking/LinkedReportsIndicator',
    component: LinkedReportsIndicatorDisplay,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-08-10' },
}
export default meta

type Story = StoryObj<typeof LinkedReportsIndicatorDisplay>

function makeReport(overrides: Partial<SignalReportApi> = {}): SignalReportApi {
    return {
        id: '019f9582-93e7-77c1-8912-4f541d70cb13',
        status: 'ready',
        title: 'fix(replay): guard against a missing snapshot index',
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64772',
        implementation_pr_merged: false,
        ...overrides,
    } as SignalReportApi
}

const MERGED = makeReport({
    id: '019f954a-8ed0-7a18-a198-3ffed1a2def0',
    status: 'resolved',
    title: 'fix(replay): stop dropping events after a tab regains focus',
    implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64773',
    implementation_pr_merged: true,
})

const NO_PR = makeReport({
    id: '019f9569-5d45-780a-8b63-ecd0dc71148e',
    status: 'in_progress',
    title: 'fix(replay): re-key the player when the recording id changes',
    implementation_pr_url: null,
})

/** The header row this sits in, so the chip is judged next to the neighbours it has to live with. */
function HeaderRow({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <span className="text-base font-semibold">Non-OK response</span>
            <div className="flex items-center gap-1">{children}</div>
        </div>
    )
}

export const FixProposed: Story = {
    render: () => (
        <HeaderRow>
            <LinkedReportsIndicatorDisplay reports={[makeReport()]} />
        </HeaderRow>
    ),
}

export const FixMerged: Story = {
    render: () => (
        <HeaderRow>
            <LinkedReportsIndicatorDisplay reports={[MERGED]} />
        </HeaderRow>
    ),
}

export const NoPullRequestYet: Story = {
    render: () => (
        <HeaderRow>
            <LinkedReportsIndicatorDisplay reports={[NO_PR]} />
        </HeaderRow>
    ),
}

export const SeveralReports: Story = {
    render: () => (
        <HeaderRow>
            <LinkedReportsIndicatorDisplay reports={[makeReport(), MERGED, NO_PR]} />
        </HeaderRow>
    ),
}
