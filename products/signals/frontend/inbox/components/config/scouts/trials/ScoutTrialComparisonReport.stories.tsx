import type { Meta, StoryObj } from '@storybook/react'

import { scoutRubricReferenceFixture } from '../scoutRubricFixtures'
import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import { trialFixtureLongReport, trialFixtureReport } from './scoutTrialsFixtures'

const meta: Meta<typeof ScoutTrialComparisonReport> = {
    title: 'Scenes-App/Inbox/Scout comparison report',
    component: ScoutTrialComparisonReport,
    args: { report: trialFixtureReport },
    parameters: { layout: 'padded' },
}
export default meta
type Story = StoryObj<typeof ScoutTrialComparisonReport>

export const Completed: Story = {}
export const SavedRubric: Story = {
    args: {
        report: {
            ...trialFixtureReport,
            rubric_source: 'saved',
            rubric_revision: 2,
            rubric_reference_context: scoutRubricReferenceFixture,
            rubric_reference_generation_id: '00000000-0000-4000-8000-000000000032',
            limitations: ['Live data may change between runs. These scores describe the captured sample.'],
        },
    },
}
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
            outcome: {
                status: 'inconclusive',
                variant_ids: [],
                summary:
                    'One check has too little evidence, and one run could not be judged. These results cannot identify the best variant.',
            },
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

export const Tie: Story = {
    args: {
        report: {
            ...trialFixtureLongReport,
            outcome: {
                status: 'tie',
                variant_ids: trialFixtureLongReport.variants.map((variant) => variant.variant_id),
                summary: 'Both variants tied: each passed 24 of 24 rubric checks across 2 runs.',
            },
            variants: trialFixtureLongReport.variants.map((variant) => ({
                ...variant,
                score: 1,
                baseline_delta: variant.is_baseline ? null : 0,
                criteria: variant.criteria.map((criterion) => ({
                    ...criterion,
                    passed: 2,
                    failed: 0,
                    pass_rate: 1,
                    baseline_delta: variant.is_baseline ? null : 0,
                })),
            })),
            runs: trialFixtureLongReport.runs.map((run) => ({
                ...run,
                score: 1,
                criteria: run.criteria?.map((criterion) => ({
                    ...criterion,
                    verdict: 'pass',
                    reason: 'The captured scout output satisfies this check.',
                })),
            })),
        },
    },
}

export const TwelveRubrics: Story = {
    args: { report: trialFixtureLongReport },
}

export const TwelveRubricsNarrow: Story = {
    ...Narrow,
    args: { report: trialFixtureLongReport },
}

export const SavedWithoutConclusion: Story = {
    args: { report: { ...trialFixtureReport, outcome: null } },
}
