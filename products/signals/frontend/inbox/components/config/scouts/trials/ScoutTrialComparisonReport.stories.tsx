import type { Meta, StoryObj } from '@storybook/react'

import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import { trialFixtureReport } from './scoutTrialsFixtures'

const meta: Meta<typeof ScoutTrialComparisonReport> = {
    title: 'Scenes-App/Inbox/Scout comparison report',
    component: ScoutTrialComparisonReport,
    args: { report: trialFixtureReport },
    parameters: { layout: 'padded' },
}
export default meta
type Story = StoryObj<typeof ScoutTrialComparisonReport>

export const Completed: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
export const PartialEvidence: Story = {
    args: {
        report: {
            ...trialFixtureReport,
            summary: 'The candidate has incomplete evidence. Its score cannot be compared with the baseline.',
            variants: trialFixtureReport.variants.map((variant) =>
                variant.is_baseline
                    ? variant
                    : {
                          ...variant,
                          score: 1,
                          coverage: 0.5,
                          baseline_delta: null,
                          judged_runs: 1,
                          judge_errors: 1,
                          criteria: variant.criteria.map((criterion) => ({
                              ...criterion,
                              passed: criterion.criterion_id === 'evidence' ? 1 : 0,
                              failed: 0,
                              unknown: criterion.criterion_id === 'action' ? 1 : 0,
                              pass_rate: criterion.criterion_id === 'evidence' ? 1 : null,
                              coverage: criterion.criterion_id === 'evidence' ? 1 : 0,
                              baseline_delta: null,
                          })),
                      }
            ),
            runs: trialFixtureReport.runs.map((run, index) =>
                index < 2
                    ? run
                    : index === 3
                      ? {
                            ...run,
                            status: 'judge_error',
                            score: null,
                            coverage: null,
                            criteria: [],
                            error: 'The judge response could not be validated.',
                        }
                      : {
                            ...run,
                            coverage: 0.5,
                            criteria: run.criteria?.map((criterion) =>
                                criterion.criterion_id === 'evidence'
                                    ? criterion
                                    : {
                                          ...criterion,
                                          verdict: 'unknown',
                                          confidence: 'low',
                                          reason: 'The captured evidence does not establish whether the action is feasible.',
                                          evidence: [],
                                      }
                            ),
                        }
            ),
        },
    },
}
