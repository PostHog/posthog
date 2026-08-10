import type { Meta, StoryObj } from '@storybook/react'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { LinkedReportsSection } from './LinkedReports'

// The issue side panel's view of what the inbox already found for this error. Whether a fix exists is
// the headline, so one story carries the PR states next to the statuses that stand in when there's no PR.

const meta: Meta<typeof LinkedReportsSection> = {
    title: 'Scenes-App/ErrorTracking/LinkedReportsSection',
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
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64772',
        implementation_pr_merged: false,
        ...overrides,
    } as SignalReportApi
}

export const SeveralReportsAcrossStates: Story = {
    render: () => (
        // The panel column is 300px wide with 8px of padding either side.
        <div className="w-[284px]">
            <LinkedReportsSection
                reports={[
                    makeReport(),
                    makeReport({
                        id: '019f954a-8ed0-7a18-a198-3ffed1a2def0',
                        status: 'resolved',
                        title: 'fix(replay): stop dropping events after a tab regains focus',
                        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/64773',
                        implementation_pr_merged: true,
                    }),
                    makeReport({
                        id: '019f9569-5d45-780a-8b63-ecd0dc71148e',
                        status: 'in_progress',
                        title: 'fix(replay): re-key the player when the recording id changes',
                        implementation_pr_url: null,
                    }),
                    makeReport({
                        id: '019f95a1-2c6b-7d4e-9f01-7b2ac3e5d840',
                        status: 'pending_input',
                        title: null,
                        implementation_pr_url: null,
                    }),
                ]}
            />
        </div>
    ),
}
