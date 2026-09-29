import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigTrial,
    signalsScoutConfigTrialComparisonCreate,
    signalsScoutConfigTrialComparisonRetrieve,
    signalsScoutConfigTrialComparisonHistory,
    signalsScoutConfigTrialComparisonResume,
    signalsScoutConfigTrialEvaluationCreate,
    signalsScoutConfigTrialEvaluationRetrieve,
    signalsScoutConfigTrialHistory,
    signalsScoutConfigTrialResult,
    signalsScoutConfigTrialSetup,
} from 'products/signals/frontend/generated/api'
import type {
    ScoutTrialEvaluationApi,
    ScoutTrialResultApi,
    ScoutTrialComparisonApi,
} from 'products/signals/frontend/generated/api.schemas'

import {
    trialFixtureConfig,
    trialFixtureServerComparison,
    trialFixtureComparison,
    trialFixtureEvaluation,
    trialFixtureEvaluationWithJudgeError,
    trialFixtureResult,
    trialFixtureSetup,
} from '../components/config/scouts/trials/scoutTrialsFixtures'
import { scoutTrialsLogic } from './scoutTrialsLogic'

jest.mock('products/signals/frontend/generated/api', () => ({
    ...jest.requireActual('products/signals/frontend/generated/api'),
    signalsScoutConfigList: jest.fn(),
    signalsScoutConfigTrial: jest.fn(),
    signalsScoutConfigTrialComparisonCreate: jest.fn(),
    signalsScoutConfigTrialComparisonRetrieve: jest.fn(),
    signalsScoutConfigTrialComparisonHistory: jest.fn(),
    signalsScoutConfigTrialComparisonResume: jest.fn(),
    signalsScoutConfigTrialEvaluationCreate: jest.fn(),
    signalsScoutConfigTrialEvaluationRetrieve: jest.fn(),
    signalsScoutConfigTrialHistory: jest.fn(),
    signalsScoutConfigTrialResult: jest.fn(),
    signalsScoutConfigTrialSetup: jest.fn(),
}))

describe('scoutTrialsLogic', () => {
    let logic: ReturnType<typeof scoutTrialsLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        localStorage.clear()
        initKeaTests(false)
        jest.mocked(signalsScoutConfigList).mockResolvedValue([trialFixtureConfig])
        jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue(trialFixtureSetup)
        jest.mocked(signalsScoutConfigTrialHistory).mockResolvedValue({ results: [], has_more: false })
        jest.mocked(signalsScoutConfigTrialEvaluationRetrieve).mockRejectedValue(new ApiError('Not found', 404))
        jest.mocked(signalsScoutConfigTrialEvaluationCreate).mockImplementation(async (_, __, request) => ({
            ...trialFixtureEvaluation,
            evaluation_id: request.evaluation_id,
            status: 'running',
            request,
            report: null,
        }))
        jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, params) => ({
            ...trialFixtureResult,
            launch_id: params.launch_id,
        }))
        jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({ results: [], has_more: false })
        jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockRejectedValue(new ApiError('Not found', 404))
        jest.mocked(signalsScoutConfigTrialComparisonResume).mockResolvedValue({
            ...trialFixtureServerComparison,
            status: 'running',
            evaluation: null,
        })
        jest.mocked(signalsScoutConfigTrialComparisonCreate).mockImplementation(async (_, __, request) => ({
            ...trialFixtureServerComparison,
            comparison_id: request.comparison_id,
            baseline_variant_id: request.baseline_variant_id,
            variants: request.variants.map((variant) => ({ ...variant, skill_body_sha256: 'a'.repeat(64) })),
            status: 'running',
            evaluation: null,
        }))
        logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('submits the complete variant plan once so running and judging do not depend on the browser staying open', async () => {
        logic.actions.setRepeats(2)
        logic.actions.setNote('Investigate checkout retries.')
        logic.actions.updateVariant('1', {
            replacePrompt: true,
            prompt: 'Confirm each checkout failure against events.',
        })

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()

        expect(signalsScoutConfigTrialComparisonCreate).toHaveBeenCalledTimes(1)
        const request = jest.mocked(signalsScoutConfigTrialComparisonCreate).mock.calls[0][2]
        expect(request.variants).toHaveLength(2)
        const ids = request.variants.flatMap((variant) => variant.launch_ids)
        expect(ids).toHaveLength(4)
        expect(new Set(ids).size).toBe(4)
        expect(request.note).toBe('Investigate checkout retries.')
        expect(request.variants[0].skill_body).toBeUndefined()
        expect(request.variants[1].skill_body).toBe('Confirm each checkout failure against events.')
        expect(logic.values.hasUnaccepted).toBe(false)
        expect(logic.values.comparisonState.value?.status).toBe('running')
        expect(logic.values.managedComparison).toBe(true)
        expect(signalsScoutConfigTrial).not.toHaveBeenCalled()
        expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
    })

    it('retries an uncertain start with the exact same plan and does not submit an accepted comparison again', async () => {
        jest.mocked(signalsScoutConfigTrialComparisonCreate).mockRejectedValueOnce(
            new Error('Connection closed after submission')
        )
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        const firstRequest = jest.mocked(signalsScoutConfigTrialComparisonCreate).mock.calls[0][2]
        expect(logic.values.hasUnaccepted).toBe(true)

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(jest.mocked(signalsScoutConfigTrialComparisonCreate).mock.calls[1][2]).toEqual(firstRequest)

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialComparisonCreate).toHaveBeenCalledTimes(2)
    })

    it('blocks duplicate clicks while starting is in flight', async () => {
        let resolveFirst!: (value: ScoutTrialComparisonApi) => void
        jest.mocked(signalsScoutConfigTrialComparisonCreate).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveFirst = resolve
                })
        )
        logic.actions.submitComparison()
        logic.actions.submitComparison()
        expect(signalsScoutConfigTrialComparisonCreate).toHaveBeenCalledTimes(1)
        const request = jest.mocked(signalsScoutConfigTrialComparisonCreate).mock.calls[0][2]

        await expectLogic(logic, () =>
            resolveFirst({
                ...trialFixtureServerComparison,
                comparison_id: request.comparison_id,
                baseline_variant_id: request.baseline_variant_id,
                variants: request.variants.map((variant) => ({ ...variant, skill_body_sha256: 'a'.repeat(64) })),
                status: 'running',
                evaluation: null,
            })
        ).toFinishAllListeners()
        expect(logic.values.submitting).toBe(false)
    })

    it('recognizes an accepted plan recovered from history after the start response was lost', async () => {
        jest.mocked(signalsScoutConfigTrialComparisonCreate).mockImplementationOnce(async (_, __, request) => {
            jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({
                results: [
                    {
                        ...trialFixtureServerComparison,
                        comparison_id: request.comparison_id,
                        baseline_variant_id: request.baseline_variant_id,
                        variants: request.variants.map((variant) => ({
                            ...variant,
                            skill_body_sha256: 'a'.repeat(64),
                        })),
                        status: 'running',
                        evaluation: null,
                    },
                ],
                has_more: false,
            })
            throw new Error('Connection closed after saving the plan')
        })

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(logic.values.hasUnaccepted).toBe(false)
        expect(logic.values.comparisonState.error).toBeNull()
        expect(logic.values.comparisonState.value?.status).toBe('running')
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialComparisonCreate).toHaveBeenCalledTimes(1)
    })

    it('polls runs that the server has not launched yet and shows the automatic report without another submission', async () => {
        logic.unmount()
        jest.useFakeTimers()
        const visibility = jest.spyOn(document, 'hidden', 'get').mockReturnValue(false)
        try {
            jest.mocked(signalsScoutConfigTrialResult).mockResolvedValue({
                ...trialFixtureResult,
                status: 'not_started',
                task_status: null,
            })
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
            expect(logic.values.comparisonRows.every((row) => row.status === 'not_started')).toBe(true)
            const saved = logic.values.comparisonState.value!
            jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue({ ...saved, status: 'judging' })
            jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, params) => ({
                ...trialFixtureResult,
                launch_id: params.launch_id,
            }))

            await jest.advanceTimersByTimeAsync(10_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.comparisonRows.every((row) => row.status === 'completed')).toBe(true)
            expect(logic.values.comparisonState.value?.status).toBe('judging')

            jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue({
                ...saved,
                status: 'completed',
                evaluation: trialFixtureEvaluation,
            })
            await jest.advanceTimersByTimeAsync(10_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.evaluationState.value?.report).toEqual(trialFixtureEvaluation.report)

            jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({
                results: [{ ...saved, status: 'completed', evaluation: null }],
                has_more: false,
            })
            await expectLogic(logic, () =>
                logic.actions.loadComparisonHistory(trialFixtureConfig.id)
            ).toFinishAllListeners()
            expect(logic.values.evaluationState.value?.report).toEqual(trialFixtureEvaluation.report)
            expect(signalsScoutConfigTrialComparisonCreate).toHaveBeenCalledTimes(1)
            expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
        } finally {
            visibility.mockRestore()
            jest.useRealTimers()
        }
    })

    it('reuses completed results during background refresh and reloads them on explicit refresh', async () => {
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        jest.mocked(signalsScoutConfigTrialResult).mockClear()

        await expectLogic(logic, () => logic.actions.refreshResults()).toFinishAllListeners()
        expect(signalsScoutConfigTrialResult).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.refreshResults(true)).toFinishAllListeners()
        expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(2)
    })

    test.each([
        ['failed', 'not_started'],
        ['failed', 'queued'],
        ['failed', 'in_progress'],
        ['unknown', null],
    ])('keeps polling status=%s with task status=%s', async (status, taskStatus) => {
        logic.unmount()
        jest.useFakeTimers()
        const visibility = jest.spyOn(document, 'hidden', 'get').mockReturnValue(false)
        try {
            jest.mocked(signalsScoutConfigTrialResult).mockResolvedValue({
                ...trialFixtureResult,
                status: status!,
                task_status: taskStatus,
            })
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId: trialFixtureResult.launch_id }])
            await expectLogic(logic, () => logic.actions.refreshResults()).toFinishAllListeners()
            jest.mocked(signalsScoutConfigTrialResult).mockClear()

            await jest.advanceTimersByTimeAsync(10_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(signalsScoutConfigTrialResult).toHaveBeenCalled()
        } finally {
            visibility.mockRestore()
            jest.useRealTimers()
        }
    })

    it('loads the newly selected scout after an older result request finishes', async () => {
        let resolveOld!: (value: ScoutTrialResultApi) => void
        jest.mocked(signalsScoutConfigTrialResult).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveOld = resolve
                })
        )
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId: trialFixtureResult.launch_id }])
        logic.actions.refreshResults()
        const newConfig = '00000000-0000-4000-8000-000000000010'
        const newLaunch = '00000000-0000-4000-8000-000000000011'
        jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue({ ...trialFixtureSetup, config_id: newConfig })
        jest.mocked(signalsScoutConfigTrialHistory).mockResolvedValue({
            results: [
                {
                    launch_id: newLaunch,
                    context_id: trialFixtureResult.context_id,
                    variant: 'Saved variant',
                    model: trialFixtureResult.model,
                    reasoning_effort: trialFixtureResult.reasoning_effort,
                    status: 'completed',
                    started_at: trialFixtureResult.started_at!,
                    completed_at: trialFixtureResult.completed_at,
                    run_id: trialFixtureResult.run_id!,
                    task_id: trialFixtureResult.task_id!,
                    task_run_id: trialFixtureResult.task_run_id!,
                },
            ],
            has_more: false,
        })

        await expectLogic(logic, () => logic.actions.selectConfig(newConfig)).toDispatchActions(['loadHistorySuccess'])
        await expectLogic(logic, () => resolveOld(trialFixtureResult)).toFinishAllListeners()

        expect(logic.values.results[newLaunch]?.launch_id).toBe(newLaunch)
        expect(logic.values.rows.map((row) => row.launchId)).toEqual([newLaunch])
    })

    it('restores accepted run IDs without storing prompts or captured content and isolates browser state by user', async () => {
        logic.actions.setNote('Private investigation instructions')
        logic.actions.updateVariant('1', {
            label: 'Private variant label',
            replacePrompt: true,
            prompt: 'Private replacement prompt',
        })
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        const tracked = logic.values.tracked
        const comparison = logic.values.selectedComparison
        jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue({
            ...logic.values.comparisonState.value!,
            status: 'completed',
            evaluation: trialFixtureEvaluation,
        })
        logic.actions.updateEvaluation(comparison!.id, { value: trialFixtureEvaluation })
        const stored = JSON.stringify(localStorage)
        expect(stored).not.toContain('Private replacement prompt')
        expect(stored).not.toContain('Private investigation instructions')
        expect(stored).not.toContain('Coupon removal')
        expect(stored).not.toContain('Private variant label')
        expect(stored).not.toContain(trialFixtureEvaluation.report!.summary)
        expect(stored).toContain(comparison!.id)
        logic.unmount()

        logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(logic.values.tracked).toEqual(tracked)
        expect(logic.values.batch).toBeNull()
        expect(logic.values.note).toBe('')
        expect(logic.values.selectedComparison).toEqual(comparison)
        expect(logic.values.evaluationState.value?.report).toEqual(trialFixtureEvaluation.report)
        expect(logic.values.comparisonState.value?.status).toBe('completed')
        expect(signalsScoutConfigTrialComparisonRetrieve).toHaveBeenLastCalledWith('2', trialFixtureConfig.id, {
            comparison_id: comparison!.id,
        })
        expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
        const otherUser = scoutTrialsLogic({ teamId: 2, userId: 43 })
        await expectLogic(otherUser, () => {
            otherUser.mount()
        }).toFinishAllListeners()
        expect(otherUser.values.tracked).toEqual([])
        expect(otherUser.values.comparisons).toEqual([])
        otherUser.unmount()
    })

    it('recovers a server-saved comparison without browser history and only reads its automatically judged report', async () => {
        jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({
            results: [trialFixtureServerComparison],
            has_more: false,
        })
        jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue(trialFixtureServerComparison)

        await expectLogic(logic, () =>
            logic.actions.loadComparisonHistory(trialFixtureConfig.id)
        ).toFinishAllListeners()

        expect(logic.values.selectedComparison?.id).toBe(trialFixtureServerComparison.comparison_id)
        expect(logic.values.evaluationState.value?.report).toEqual(trialFixtureServerComparison.evaluation?.report)
        expect(logic.values.comparisonRows).toHaveLength(4)
        expect(signalsScoutConfigTrialComparisonCreate).not.toHaveBeenCalled()
        expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
    })

    it('resumes a restored comparison by ID without resubmitting its private prompt and blocks duplicate retries', async () => {
        logic.actions.registerServerComparison({ ...trialFixtureServerComparison, status: 'failed', evaluation: null })
        jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue({
            ...trialFixtureServerComparison,
            status: 'failed',
            evaluation: null,
        })
        await expectLogic(logic, () =>
            logic.actions.selectComparison(trialFixtureComparison.configId, trialFixtureComparison.id)
        ).toFinishAllListeners()
        let resolveResume!: (value: ScoutTrialComparisonApi) => void
        jest.mocked(signalsScoutConfigTrialComparisonResume).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveResume = resolve
                })
        )

        logic.actions.resumeComparison()
        logic.actions.resumeComparison()
        expect(signalsScoutConfigTrialComparisonResume).toHaveBeenCalledTimes(1)
        expect(signalsScoutConfigTrialComparisonResume).toHaveBeenCalledWith('2', trialFixtureConfig.id, {
            comparison_id: trialFixtureComparison.id,
        })
        await expectLogic(logic, () =>
            resolveResume({
                ...trialFixtureServerComparison,
                status: 'running',
                evaluation: null,
            })
        ).toFinishAllListeners()
        expect(logic.values.comparisonState.resuming).toBe(false)
        expect(logic.values.comparisonState.value?.status).toBe('running')
        expect(signalsScoutConfigTrialComparisonCreate).not.toHaveBeenCalled()
    })

    it('scores only explicit groups in the selected comparison and blocks duplicate submissions', async () => {
        logic.actions.registerComparison(trialFixtureComparison)
        await expectLogic(logic, () =>
            logic.actions.selectComparison(trialFixtureComparison.configId, trialFixtureComparison.id)
        ).toFinishAllListeners()
        const comparison = logic.values.selectedComparison!
        const unrelatedLaunchId = '00000000-0000-4000-8000-000000000099'
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId: unrelatedLaunchId }])
        await expectLogic(logic, () => logic.actions.refreshResults()).toFinishAllListeners()
        let resolveScore!: (response: ScoutTrialEvaluationApi) => void
        jest.mocked(signalsScoutConfigTrialEvaluationCreate).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveScore = resolve
                })
        )

        logic.actions.scoreComparison()
        logic.actions.scoreComparison()
        expect(signalsScoutConfigTrialEvaluationCreate).toHaveBeenCalledTimes(1)
        const request = jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]
        expect(request).toEqual({
            evaluation_id: comparison.id,
            baseline_variant_id: comparison.baselineVariantId,
            rubric_source: 'saved',
            variants: comparison.groups.map((group, index) => ({
                id: group.variantId,
                launch_ids: group.launchIds,
                label: `Variant ${index + 1}`,
            })),
        })
        expect(request.variants.flatMap((variant) => variant.launch_ids)).not.toContain(unrelatedLaunchId)
        await expectLogic(logic, () =>
            resolveScore({
                ...trialFixtureEvaluation,
                evaluation_id: comparison.id,
                request,
                status: 'running',
                report: null,
            })
        ).toFinishAllListeners()
        logic.actions.scoreComparison()
        expect(signalsScoutConfigTrialEvaluationCreate).toHaveBeenCalledTimes(1)
    })

    it.each([
        ['completed', trialFixtureEvaluation],
        ['completed with judge errors', trialFixtureEvaluationWithJudgeError],
        ['failed', { ...trialFixtureEvaluation, status: 'failed' as const, report: null }],
    ])(
        'prepares a fresh saved-rubric attempt from a %s evaluation without launching or scoring automatically',
        async (_label, previousEvaluation) => {
            jest.mocked(signalsScoutConfigTrialEvaluationRetrieve).mockResolvedValueOnce(previousEvaluation)
            logic.actions.registerComparison(trialFixtureComparison)
            await expectLogic(logic, () =>
                logic.actions.selectComparison(trialFixtureComparison.configId, trialFixtureComparison.id)
            ).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.newScoringAttempt()
                logic.actions.newScoringAttempt()
            }).toFinishAllListeners()

            const next = logic.values.selectedComparison!
            expect(next.id).not.toBe(trialFixtureComparison.id)
            expect(next.groups).toEqual(trialFixtureComparison.groups)
            expect(next.baselineVariantId).toBe(trialFixtureComparison.baselineVariantId)
            expect(logic.values.comparisons).toHaveLength(2)
            expect(logic.values.evaluations[trialFixtureComparison.id].value?.report).toEqual(previousEvaluation.report)
            expect(logic.values.evaluationState.preparedRequest).toEqual({
                ...previousEvaluation.request,
                evaluation_id: next.id,
                rubric_source: 'saved',
            })
            expect(logic.values.scoreDisabledReason).toBeNull()
            expect(signalsScoutConfigTrial).not.toHaveBeenCalled()
            expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()

            await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
            expect(signalsScoutConfigTrialEvaluationCreate).toHaveBeenCalledTimes(1)
            expect(jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]).toEqual({
                ...previousEvaluation.request,
                evaluation_id: next.id,
                rubric_source: 'saved',
            })
        }
    )

    it('requires a status refresh after an uncertain score submission and retries the saved request exactly', async () => {
        logic.actions.registerComparison(trialFixtureComparison)
        await expectLogic(logic, () =>
            logic.actions.selectComparison(trialFixtureComparison.configId, trialFixtureComparison.id)
        ).toFinishAllListeners()
        jest.mocked(signalsScoutConfigTrialEvaluationCreate).mockRejectedValueOnce(new Error('Connection closed'))
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        const request = jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]
        logic.actions.scoreComparison()
        expect(signalsScoutConfigTrialEvaluationCreate).toHaveBeenCalledTimes(1)

        const savedRequest = {
            ...request,
            rubric_source: 'mock' as const,
            variants: request.variants.map((variant) => ({ ...variant, label: 'Saved server label' })),
        }
        jest.mocked(signalsScoutConfigTrialEvaluationRetrieve).mockResolvedValue({
            ...trialFixtureEvaluation,
            evaluation_id: request.evaluation_id,
            request: savedRequest,
            status: 'failed',
            report: null,
        })
        await expectLogic(logic, () => logic.actions.loadEvaluation(request.evaluation_id)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[1][2]).toEqual(savedRequest)
    })

    it.each([
        'Save a reviewed rubric before scoring this comparison.',
        'Generate suggestions, adopt their reference, and save the rubric before scoring.',
    ])('shows rubric validation errors and allows an explicit retry: %s', async (message) => {
        logic.actions.registerComparison(trialFixtureComparison)
        await expectLogic(logic, () =>
            logic.actions.selectComparison(trialFixtureComparison.configId, trialFixtureComparison.id)
        ).toFinishAllListeners()
        jest.mocked(signalsScoutConfigTrialEvaluationCreate).mockRejectedValueOnce(new ApiError(message, 400))
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(logic.values.evaluationState.error).toBe(message)
        expect(logic.values.evaluationState.notStarted).toBe(true)
        expect(logic.values.scoreDisabledReason).toBeNull()
        const request = jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]

        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[1][2]).toEqual(request)
    })
})
