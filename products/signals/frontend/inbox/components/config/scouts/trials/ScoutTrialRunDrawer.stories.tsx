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
