import type { Meta, StoryObj } from '@storybook/react'

import { ScoutTrialJudgment } from './ScoutTrialJudgment'
import { trialFixtureReport } from './scoutTrialsFixtures'

const meta: Meta<typeof ScoutTrialJudgment> = {
    title: 'Scenes-App/Inbox/Scout run judgment',
    component: ScoutTrialJudgment,
    args: {
        judgment: trialFixtureReport.runs[0],
        evidence: trialFixtureReport.evidence[0],
        criteria: trialFixtureReport.criteria,
    },
    parameters: { layout: 'padded' },
}
export default meta
type Story = StoryObj<typeof ScoutTrialJudgment>

export const Evidence: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
export const Excluded: Story = {
    args: {
        judgment: {
            ...trialFixtureReport.runs[0],
            status: 'excluded',
            score: null,
            coverage: null,
            criteria: [],
            summary: 'The run was canceled before producing evidence.',
        },
        evidence: {
            ...trialFixtureReport.evidence[0],
            sources: [],
            exclusion_reason: 'The run was canceled before producing evidence.',
        },
    },
}
