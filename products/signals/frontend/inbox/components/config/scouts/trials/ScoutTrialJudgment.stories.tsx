import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { ScoutTrialJudgment } from './ScoutTrialJudgment'
import { trialFixtureLongReport, trialFixtureReport } from './scoutTrialsFixtures'

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
            execution_status: 'cancelled',
            sources: [],
            exclusion_reason: 'The run was canceled before producing evidence.',
        },
    },
}

export const TwelveRubrics: Story = {
    args: {
        judgment: trialFixtureLongReport.runs[0],
        evidence: trialFixtureLongReport.evidence[0],
        criteria: trialFixtureLongReport.criteria,
    },
}

export const TwelveRubricsNarrow: Story = {
    ...Narrow,
    ...TwelveRubrics,
}

export const ExpandedRubric: Story = {
    ...TwelveRubrics,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('Evidence grounding'))
    },
}

export const MixedVerdicts: Story = {
    ...TwelveRubrics,
    args: {
        ...TwelveRubrics.args,
        judgment: {
            ...trialFixtureLongReport.runs[0],
            score: 8 / 10,
            coverage: 10 / 11,
            criteria: trialFixtureLongReport.runs[0].criteria?.map((criterion) =>
                criterion.criterion_id === 'recurrence'
                    ? {
                          ...criterion,
                          verdict: 'unknown',
                          confidence: 'low',
                          reason: 'The captured result does not establish whether the same behavior happened more than once.',
                          evidence: [],
                      }
                    : criterion.criterion_id === 'duplicates'
                      ? {
                            ...criterion,
                            verdict: 'not_applicable',
                            reason: 'No earlier finding covers this product area.',
                            evidence: [],
                        }
                      : criterion
            ),
        },
    },
}
