import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator } from '~/mocks/browser'

import type {
    ScoutRubricDocumentApi,
    ScoutRubricSaveApi,
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
let rubric: ScoutRubricDocumentApi = {
    config_id: trialFixtureConfig.id,
    skill_name: scoutRubricReferenceFixture.skill_name,
    revision: 2,
    criteria: trialFixtureReport.criteria.map((criterion) => ({ ...criterion, enabled: true, source: 'custom' })),
    reference_context: scoutRubricReferenceFixture,
    reference_generation_id: '00000000-0000-4000-8000-000000000032',
    generation: null,
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
                '/api/projects/:team/signals/scout/configs/:config/trial_evaluation/': async ({ request }) => {
                    const payload = (await request.json()) as ScoutTrialEvaluationRequestApi
                    const existing = evaluations.get(payload.evaluation_id)
                    if (existing) {
                        return [200, existing]
                    }
                    const evaluation: ScoutTrialEvaluationApi = {
                        ...trialFixtureEvaluation,
                        evaluation_id: payload.evaluation_id,
                        request: payload,
                        report: {
                            ...trialFixtureReport,
                            rubric_source: payload.rubric_source,
                            rubric_revision: payload.rubric_source === 'saved' ? rubric.revision : 0,
                            rubric_reference_context:
                                payload.rubric_source === 'saved' ? scoutRubricReferenceFixture : null,
                            rubric_reference_generation_id:
                                payload.rubric_source === 'saved' ? rubric.reference_generation_id : null,
                            criteria: payload.rubric_source === 'saved' ? rubric.criteria : trialFixtureReport.criteria,
                            limitations: ['These fixed Storybook judgments demonstrate the scoring interface.'],
                            evaluation_id: payload.evaluation_id,
                            baseline_variant_id: payload.baseline_variant_id,
                            summary:
                                'This Storybook report uses fixed mock judgments to demonstrate scoring and evidence inspection.',
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
                                        passed:
                                            baseline && criterion.criterion_id === 'evidence'
                                                ? 0
                                                : variant.launch_ids.length,
                                        failed:
                                            baseline && criterion.criterion_id === 'evidence'
                                                ? variant.launch_ids.length
                                                : 0,
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
                                    launch_id: launchId,
                                    variant_id: variant.id,
                                    model: submissions.get(launchId)?.model ?? trialFixtureResult.model,
                                    reasoning_effort:
                                        submissions.get(launchId)?.reasoning_effort ??
                                        trialFixtureResult.reasoning_effort,
                                }))
                            ),
                        },
                    }
                    evaluations.set(payload.evaluation_id, evaluation)
                    return [202, evaluation]
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
                '/api/projects/:team/signals/scout/configs/:config/trial_result/': ({ request }) => [
                    200,
                    {
                        ...trialFixtureResult,
                        launch_id: new URL(request.url).searchParams.get('launch_id'),
                        status: 'running',
                        task_status: 'running',
                        reports: [],
                        memory: {},
                        summary: '',
                        completed_at: null,
                    },
                ],
            },
        }),
    ],
}
