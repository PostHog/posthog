import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import type {
    ScoutRubricDocumentApi,
    ScoutRubricSaveApi,
    ScoutTrialComparisonApi,
    ScoutTrialComparisonRequestApi,
    ScoutTrialComparisonQueryApi,
    ScoutTrialEvaluationApi,
    ScoutTrialEvaluationRequestApi,
    ScoutTrialLaunchApi,
} from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricReferenceFixture } from '../scoutRubricFixtures'
import { ScoutTrials } from './ScoutTrials'
import {
    trialFixtureConfig,
    trialFixtureEvaluation,
    trialFixtureReport,
    trialFixtureResult,
    trialFixtureSetup,
} from './scoutTrialsFixtures'

const submissions = new Map<string, ScoutTrialLaunchApi>()
const evaluations = new Map<string, ScoutTrialEvaluationApi>()
const comparisons = new Map<string, ScoutTrialComparisonApi>()
let rubric: ScoutRubricDocumentApi = {
    config_id: trialFixtureConfig.id,
    skill_name: scoutRubricReferenceFixture.skill_name,
    revision: 2,
    criteria: trialFixtureReport.criteria.map((criterion) => ({ ...criterion, enabled: true, source: 'custom' })),
    reference_context: scoutRubricReferenceFixture,
    reference_generation_id: '00000000-0000-4000-8000-000000000032',
    generation: null,
}

function buildEvaluation(payload: ScoutTrialEvaluationRequestApi): ScoutTrialEvaluationApi {
    const existing = evaluations.get(payload.evaluation_id)
    if (existing) {
        return existing
    }
    const candidates = payload.variants.filter((variant) => variant.id !== payload.baseline_variant_id)
    const evaluation: ScoutTrialEvaluationApi = {
        ...trialFixtureEvaluation,
        evaluation_id: payload.evaluation_id,
        request: payload,
        report: {
            ...trialFixtureReport,
            outcome: {
                status: candidates.length === 1 ? 'winner' : candidates.length > 1 ? 'tie' : 'inconclusive',
                variant_ids: candidates.map((variant) => variant.id),
                summary: candidates.length
                    ? 'The candidate variants passed every rubric check in these fixed Storybook results.'
                    : 'Add another variant to compare results.',
            },
            rubric_source: payload.rubric_source,
            rubric_revision: payload.rubric_source === 'saved' ? rubric.revision : 0,
            rubric_reference_context: payload.rubric_source === 'saved' ? scoutRubricReferenceFixture : null,
            rubric_reference_generation_id: payload.rubric_source === 'saved' ? rubric.reference_generation_id : null,
            criteria: payload.rubric_source === 'saved' ? rubric.criteria : trialFixtureReport.criteria,
            limitations: ['These fixed Storybook judgments demonstrate the scoring interface.'],
            evaluation_id: payload.evaluation_id,
            baseline_variant_id: payload.baseline_variant_id,
            summary: 'This Storybook report uses fixed mock judgments to demonstrate scoring and evidence inspection.',
            variants: payload.variants.map((variant) => {
                const baseline = variant.id === payload.baseline_variant_id
                return {
                    ...trialFixtureReport.variants[baseline ? 0 : 1],
                    variant_id: variant.id,
                    label: variant.label,
                    is_baseline: baseline,
                    total_runs: variant.launch_ids.length,
                    judged_runs: variant.launch_ids.length,
                    score: baseline ? 0.5 : 1,
                    baseline_delta: baseline ? null : 0.5,
                    criteria: trialFixtureReport.variants[0].criteria.map((criterion) => ({
                        ...criterion,
                        passed: baseline && criterion.criterion_id === 'evidence' ? 0 : variant.launch_ids.length,
                        failed: baseline && criterion.criterion_id === 'evidence' ? variant.launch_ids.length : 0,
                        pass_rate: baseline && criterion.criterion_id === 'evidence' ? 0 : 1,
                        baseline_delta: baseline ? null : criterion.criterion_id === 'evidence' ? 1 : 0,
                    })),
                }
            }),
            runs: payload.variants.flatMap((variant) =>
                variant.launch_ids.map((launchId) => ({
                    ...trialFixtureReport.runs[variant.id === payload.baseline_variant_id ? 0 : 2],
                    launch_id: launchId,
                    variant_id: variant.id,
                }))
            ),
            evidence: payload.variants.flatMap((variant) =>
                variant.launch_ids.map((launchId) => ({
                    ...trialFixtureReport.evidence[0],
                    skill_body_sha256: submissions.get(launchId)?.skill_body ? 'b'.repeat(64) : 'a'.repeat(64),
                    launch_id: launchId,
                    variant_id: variant.id,
                    model: submissions.get(launchId)?.model ?? trialFixtureResult.model,
                    reasoning_effort:
                        submissions.get(launchId)?.reasoning_effort ?? trialFixtureResult.reasoning_effort,
                }))
            ),
        },
    }
    evaluations.set(payload.evaluation_id, evaluation)
    return evaluation
}

const meta: Meta<typeof ScoutTrials> = {
    title: 'Scenes-App/Inbox/Scout comparisons interactive',
    component: ScoutTrials,
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => {
            useEffect(() => {
                teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 2 })
                userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, id: 42, is_staff: true })
            }, [])
            return <Story />
        },
        mswDecorator({
            get: {
                '/api/projects/:team/signals/scout/rubrics/:config/': () => [200, rubric],
                '/api/projects/:team/signals/scout/configs/:config/trial_comparison_history/': () => [
                    200,
                    {
                        results: [...comparisons.values()]
                            .reverse()
                            .map((comparison) => ({ ...comparison, evaluation: null })),
                        has_more: false,
                    },
                ],
                '/api/projects/:team/signals/scout/configs/:config/trial_comparison_result/': ({ request }) => {
                    const id = new URL(request.url).searchParams.get('comparison_id')!
                    const comparison = comparisons.get(id)
                    if (!comparison) {
                        return [404, { detail: 'Comparison not found.' }]
                    }
                    const status = comparison.status === 'running' ? 'judging' : 'completed'
                    const updated: ScoutTrialComparisonApi = {
                        ...comparison,
                        status,
                        evaluation: status === 'completed' ? evaluations.get(id)! : null,
                    }
                    comparisons.set(id, updated)
                    return [200, updated]
                },
                '/api/projects/:team/signals/scout/configs/:config/trial_evaluation_result/': ({ request }) => {
                    const evaluation = evaluations.get(new URL(request.url).searchParams.get('evaluation_id')!)
                    return evaluation ? [200, evaluation] : [404, { detail: 'Evaluation not found.' }]
                },
                '/api/users/@me/': () => [200, { ...MOCK_DEFAULT_USER, id: 42, is_staff: true }],
                '/api/projects/:team/signals/scout/configs/': () => [200, [trialFixtureConfig]],
                '/api/projects/:team/signals/scout/configs/:config/trial_setup/': () => [200, trialFixtureSetup],
                '/api/projects/:team/signals/scout/configs/:config/trial_history/': () => [
                    200,
                    { results: [], has_more: false },
                ],
                '/api/projects/:team/signals/scout/configs/:config/trial_result/': ({ request }) => {
                    const launchId = new URL(request.url).searchParams.get('launch_id')!
                    const submission = submissions.get(launchId)
                    return [
                        200,
                        {
                            ...trialFixtureResult,
                            launch_id: launchId,
                            model: submission?.model ?? trialFixtureResult.model,
                            reasoning_effort: submission?.reasoning_effort ?? trialFixtureResult.reasoning_effort,
                        },
                    ]
                },
            },
            put: {
                '/api/projects/:team/signals/scout/rubrics/:config/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutRubricSaveApi
                    rubric = { ...rubric, criteria: payload.criteria, revision: rubric.revision + 1 }
                    return [200, rubric]
                },
            },
            post: {
                '/api/projects/:team/signals/scout/configs/:config/trial_comparison/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutTrialComparisonRequestApi
                    const existing = comparisons.get(payload.comparison_id)
                    if (existing) {
                        return [200, existing]
                    }
                    for (const variant of payload.variants) {
                        for (const [index, launchId] of variant.launch_ids.entries()) {
                            submissions.set(launchId, {
                                launch_id: launchId,
                                variant: `${variant.label} (${index + 1})`,
                                model: variant.model,
                                reasoning_effort: variant.reasoning_effort,
                                ...(variant.skill_body ? { skill_body: variant.skill_body } : {}),
                            })
                        }
                    }
                    buildEvaluation({
                        evaluation_id: payload.comparison_id,
                        baseline_variant_id: payload.baseline_variant_id,
                        rubric_source: 'saved',
                        variants: payload.variants.map((variant) => ({
                            id: variant.id,
                            label: variant.label,
                            launch_ids: variant.launch_ids,
                        })),
                    })
                    const comparison: ScoutTrialComparisonApi = {
                        comparison_id: payload.comparison_id,
                        config_id: trialFixtureConfig.id,
                        context_id: trialFixtureResult.context_id,
                        created_at: '2026-01-01T10:00:00Z',
                        baseline_variant_id: payload.baseline_variant_id,
                        rubric_revision: rubric.revision,
                        variants: payload.variants.map((variant) => ({
                            id: variant.id,
                            label: variant.label,
                            launch_ids: variant.launch_ids,
                            model: variant.model,
                            reasoning_effort: variant.reasoning_effort,
                            skill_body_sha256: variant.skill_body ? 'b'.repeat(64) : 'a'.repeat(64),
                        })),
                        status: 'running',
                        error: null,
                        evaluation: null,
                    }
                    comparisons.set(payload.comparison_id, comparison)
                    return [202, comparison]
                },
                '/api/projects/:team/signals/scout/configs/:config/trial_comparison_resume/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutTrialComparisonQueryApi
                    const comparison = comparisons.get(payload.comparison_id)
                    return comparison ? [202, comparison] : [404, { detail: 'Comparison not found.' }]
                },
                '/api/projects/:team/signals/scout/configs/:config/trial_evaluation/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutTrialEvaluationRequestApi
                    return [202, buildEvaluation(payload)]
                },
                '/api/projects/:team/signals/scout/configs/:config/trial/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutTrialLaunchApi
                    submissions.set(payload.launch_id, payload)
                    return [
                        202,
                        {
                            launch_id: payload.launch_id,
                            context_id: trialFixtureResult.context_id,
                            workflow_id: payload.launch_id,
                            model: payload.model,
                            reasoning_effort: payload.reasoning_effort,
                            variant: payload.variant,
                        },
                    ]
                },
                '/api/projects/:team/tasks/:task/runs/:run/cancel/': () => [200, {}],
            },
        }),
    ],
}
export default meta
type Story = StoryObj<typeof ScoutTrials>

export const Interactive: Story = {}
export const Running: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team/signals/scout/configs/:config/trial_comparison_result/': ({ request }) => {
                    const comparison = comparisons.get(new URL(request.url).searchParams.get('comparison_id')!)
                    return comparison
                        ? [200, { ...comparison, status: 'running', evaluation: null }]
                        : [404, { detail: 'Comparison not found.' }]
                },
                '/api/projects/:team/signals/scout/configs/:config/trial_result/': ({ request }) => {
                    const launchId = new URL(request.url).searchParams.get('launch_id')!
                    const submission = submissions.get(launchId)
                    return [
                        200,
                        {
                            ...trialFixtureResult,
                            launch_id: launchId,
                            model: submission?.model ?? trialFixtureResult.model,
                            reasoning_effort: submission?.reasoning_effort ?? trialFixtureResult.reasoning_effort,
                            status: 'running',
                            task_status: 'in_progress',
                            reports: [],
                            memory: {},
                            summary: '',
                            completed_at: null,
                        },
                    ]
                },
            },
        }),
    ],
}
