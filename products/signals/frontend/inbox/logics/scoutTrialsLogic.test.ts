import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutConfigList,
    signalsScoutConfigTrial,
    signalsScoutConfigTrialEvaluationCreate,
    signalsScoutConfigTrialEvaluationRetrieve,
    signalsScoutConfigTrialHistory,
    signalsScoutConfigTrialResult,
    signalsScoutConfigTrialSetup,
} from 'products/signals/frontend/generated/api'
import type {
    ScoutTrialEvaluationApi,
    ScoutTrialResultApi,
    ScoutTrialStartedApi,
} from 'products/signals/frontend/generated/api.schemas'

import {
    trialFixtureConfig,
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
        jest.mocked(signalsScoutConfigTrial).mockImplementation(async (_, __, request) => ({
            launch_id: request.launch_id,
            context_id: trialFixtureResult.context_id,
            workflow_id: request.launch_id,
            model: request.model!,
            reasoning_effort: request.reasoning_effort!,
            variant: request.variant!,
        }))
        logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('shares the first saved context across all variants and repetitions without waiting for a run to finish', async () => {
        logic.actions.setRepeats(2)
        logic.actions.setNote('Investigate checkout retries.')
        logic.actions.updateVariant('1', {
            replacePrompt: true,
            prompt: 'Confirm each checkout failure against events.',
        })

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()

        const requests = jest.mocked(signalsScoutConfigTrial).mock.calls.map((call) => call[2])
        expect(requests).toHaveLength(4)
        expect(new Set(requests.map((request) => request.launch_id)).size).toBe(4)
        expect(requests[0].context_id).toBeUndefined()
        expect(requests.slice(1).every((request) => request.context_id === trialFixtureResult.context_id)).toBe(true)
        expect(requests.every((request) => request.note === 'Investigate checkout retries.')).toBe(true)
        expect(requests.slice(0, 2).every((request) => request.skill_body === undefined)).toBe(true)
        expect(
            requests.slice(2).every((request) => request.skill_body === 'Confirm each checkout failure against events.')
        ).toBe(true)
        expect(logic.values.hasUnaccepted).toBe(false)
    })

    it('retries an uncertain submission with the exact same body and does not repeat accepted submissions', async () => {
        jest.mocked(signalsScoutConfigTrial).mockRejectedValueOnce(new Error('Connection closed after submission'))
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        const firstRequest = jest.mocked(signalsScoutConfigTrial).mock.calls[0][2]
        expect(logic.values.hasUnaccepted).toBe(true)

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(jest.mocked(signalsScoutConfigTrial).mock.calls[1][2]).toEqual(firstRequest)
        expect(signalsScoutConfigTrial).toHaveBeenCalledTimes(3)

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrial).toHaveBeenCalledTimes(3)
    })

    it('blocks duplicate clicks while the first submission is still in flight', async () => {
        let resolveFirst!: (value: ScoutTrialStartedApi) => void
        jest.mocked(signalsScoutConfigTrial).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveFirst = resolve
                })
        )
        logic.actions.submitComparison()
        logic.actions.submitComparison()
        expect(signalsScoutConfigTrial).toHaveBeenCalledTimes(1)
        const request = jest.mocked(signalsScoutConfigTrial).mock.calls[0][2]

        await expectLogic(logic, () =>
            resolveFirst({
                launch_id: request.launch_id,
                context_id: trialFixtureResult.context_id,
                workflow_id: request.launch_id,
                model: request.model!,
                reasoning_effort: request.reasoning_effort!,
                variant: request.variant!,
            })
        ).toFinishAllListeners()
        expect(signalsScoutConfigTrial).toHaveBeenCalledTimes(2)
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
        ['failed', 'running'],
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
        expect(signalsScoutConfigTrialEvaluationRetrieve).toHaveBeenLastCalledWith('2', trialFixtureConfig.id, {
            evaluation_id: comparison!.id,
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

    it('scores only explicit groups in the selected comparison and blocks duplicate submissions', async () => {
        logic.actions.setRepeats(2)
        logic.actions.updateVariant('1', { label: 'Candidate (with parentheses)' })
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        const comparison = logic.values.selectedComparison!
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId: trialFixtureResult.launch_id }])
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
            rubric_source: 'mock',
            variants: comparison.groups.map((group, index) => ({
                id: group.variantId,
                launch_ids: group.launchIds,
                label: index === 0 ? 'Baseline' : 'Candidate (with parentheses)',
            })),
        })
        expect(request.variants.flatMap((variant) => variant.launch_ids)).not.toContain(trialFixtureResult.launch_id)
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

    it('prepares a fresh scoring attempt for the same runs without launching or scoring automatically', async () => {
        jest.mocked(signalsScoutConfigTrialEvaluationRetrieve).mockResolvedValueOnce(
            trialFixtureEvaluationWithJudgeError
        )
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
        expect(logic.values.evaluations[trialFixtureComparison.id].value?.report).toEqual(
            trialFixtureEvaluationWithJudgeError.report
        )
        expect(logic.values.evaluationState.preparedRequest).toEqual({
            ...trialFixtureEvaluationWithJudgeError.request,
            evaluation_id: next.id,
        })
        expect(logic.values.scoreDisabledReason).toBeNull()
        expect(signalsScoutConfigTrial).not.toHaveBeenCalled()
        expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialEvaluationCreate).toHaveBeenCalledTimes(1)
        expect(jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]).toEqual({
            ...trialFixtureEvaluationWithJudgeError.request,
            evaluation_id: next.id,
        })
    })

    it('requires a status refresh after an uncertain score submission and retries the saved request exactly', async () => {
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        jest.mocked(signalsScoutConfigTrialEvaluationCreate).mockRejectedValueOnce(new Error('Connection closed'))
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        const request = jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]
        logic.actions.scoreComparison()
        expect(signalsScoutConfigTrialEvaluationCreate).toHaveBeenCalledTimes(1)

        const savedRequest = {
            ...request,
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
})
