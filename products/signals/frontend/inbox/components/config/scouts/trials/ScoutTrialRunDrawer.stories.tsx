import type { Meta, StoryObj } from '@storybook/react'

import { ScoutTrialRunDrawer } from './ScoutTrialRunDrawer'
import { trialFixtureLongReport, trialFixtureResult } from './scoutTrialsFixtures'

const meta: Meta<typeof ScoutTrialRunDrawer> = {
    title: 'Scenes-App/Inbox/Scout trial run drawer',
    component: ScoutTrialRunDrawer,
    args: { result: trialFixtureResult, report: trialFixtureLongReport, onClose: () => {} },
    parameters: { layout: 'fullscreen' },
}
export default meta
type Story = StoryObj<typeof ScoutTrialRunDrawer>

export const Judged: Story = {}
export const EvidenceWithoutRunDetails: Story = {
    args: { result: null, launchId: trialFixtureLongReport.runs[0].launch_id },
}
export const UpdatedReport: Story = {
    args: {
        report: null,
        result: {
            ...trialFixtureResult,
            summary: 'Added corroborating evidence to an existing report. No new report was created.',
            reports: [
                {
                    id: '00000000-0000-4000-8000-000000000097',
                    source_report_id: '00000000-0000-4000-8000-000000000097',
                    document: {
                        title: 'Coupon removal clears the delivery choice',
                        summary: 'Removing a coupon resets the selected delivery option.',
                    },
                    edits: [{ append_note: 'A second synthetic checkout reproduced the same delivery reset.' }],
                    evidence: [
                        {
                            content: 'The delivery option changed from express to standard after removing the coupon.',
                            source_id: 'synthetic-checkout-2',
                            weight: 1,
                        },
                    ],
                    artefacts: [
                        {
                            type: 'note',
                            content: { note: 'A second synthetic checkout reproduced the same delivery reset.' },
                        },
                    ],
                },
            ],
        },
    },
}
export const Failed: Story = {
    args: {
        report: null,
        result: {
            ...trialFixtureResult,
            status: 'failed',
            error: 'The scout exceeded its time limit before writing a report.',
            summary: '',
            reports: [],
            memory: {},
        },
    },
}
export const DetailsUnavailable: Story = {
    args: {
        result: null,
        report: null,
        launchId: trialFixtureResult.launch_id,
        error: 'Run details could not be loaded. Close this panel and refresh the trial to try again.',
    },
}
