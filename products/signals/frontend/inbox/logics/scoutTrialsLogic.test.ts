jest.unmock('lib/utils/concurrencyController')

import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { promiseResolveReject } from 'lib/utils/async'

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
import { tasksRunsCancelCreate } from 'products/tasks/frontend/generated/api'

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

jest.mock('products/tasks/frontend/generated/api', () => ({
    ...jest.requireActual('products/tasks/frontend/generated/api'),
    tasksRunsCancelCreate: jest.fn(),
}))

describe('scoutTrialsLogic', () => {
    let logic: ReturnType<typeof scoutTrialsLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        localStorage.clear()
        initKeaTests(false)
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], { [FEATURE_FLAGS.SCOUT_TRIALS]: true })
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

    test.each([false, undefined, 'test'])('blocks new trials when the flag is %s', async (enabled) => {
        featureFlagLogic.actions.setFeatureFlags(
            [],
            enabled === undefined ? {} : { [FEATURE_FLAGS.SCOUT_TRIALS]: enabled }
        )

        await expectLogic(logic, () => {
            logic.actions.newComparison()
            logic.actions.submitComparison()
        }).toFinishAllListeners()

        expect(logic.values.trialView).toBe('list')
        expect(logic.values.batch).toBeNull()
        expect(signalsScoutConfigTrialComparisonCreate).not.toHaveBeenCalled()
    })

    test.each([true, false])(
        'keeps a scout-scoped trial page on its requested scout when available=%s',
        async (available) => {
            const configId = '00000000-0000-4000-8000-000000000010'
            const config = { ...trialFixtureConfig, id: configId, display_name: 'Zebra activity' }
            jest.mocked(signalsScoutConfigList).mockResolvedValue(
                available ? [trialFixtureConfig, config] : [trialFixtureConfig]
            )
            jest.mocked(signalsScoutConfigTrialSetup).mockClear()
            jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue({ ...trialFixtureSetup, config_id: configId })
            const scopedLogic = scoutTrialsLogic({ teamId: 2, userId: 42, configId })

            try {
                await expectLogic(scopedLogic, () => {
                    scopedLogic.mount()
                }).toFinishAllListeners()

                expect(logic.values.selectedConfigId).toBe(trialFixtureConfig.id)
                expect(scopedLogic.values.selectedConfigId).toBe(available ? configId : null)
                if (available) {
                    expect(scopedLogic.values.setup?.config_id).toBe(configId)
                    expect(signalsScoutConfigTrialSetup).toHaveBeenCalledWith('2', configId)
                    expect(scopedLogic.values.trialView).toBe('list')
                } else {
                    expect(scopedLogic.values.pageError).toContain('This scout is unavailable')
                    expect(signalsScoutConfigTrialSetup).not.toHaveBeenCalled()
                }
            } finally {
                scopedLogic.unmount()
            }
        }
    )

    it('keeps the baseline and at least two versions without changing repeats when adding a version', async () => {
        const baselineId = logic.values.variants[0].id
        const candidateId = logic.values.variants[1].id
        logic.actions.removeVariant(candidateId)
        expect(logic.values.variants.map((variant) => variant.id)).toEqual([baselineId, candidateId])

        logic.actions.setRepeats(10)
        await expectLogic(logic, () => logic.actions.addVariant()).toFinishAllListeners()
        expect(logic.values.variants).toHaveLength(3)
        expect(logic.values.repeats).toBe(10)
        expect(logic.values.totalRuns).toBe(30)
        expect(logic.values.formError).toBeNull()

        logic.actions.removeVariant(baselineId)
        expect(logic.values.variants).toHaveLength(3)
        logic.actions.removeVariant(candidateId)
        expect(logic.values.variants).toHaveLength(2)
        expect(logic.values.variants[0].id).toBe(baselineId)
    })

    it.each([2, 20])('submits all 20 versions with %s runs each and retains their result tracking', async (repeats) => {
        logic.actions.setRepeats(repeats)
        await expectLogic(logic, () => {
            for (let index = 2; index < 20; index++) {
                logic.actions.addVariant()
            }
            logic.actions.addVariant()
        }).toFinishAllListeners()
        expect(logic.values.variants).toHaveLength(20)
        expect(logic.values.repeats).toBe(repeats)
        expect(logic.values.totalRuns).toBe(20 * repeats)
        expect(logic.values.formError).toBeNull()

        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        const request = jest.mocked(signalsScoutConfigTrialComparisonCreate).mock.calls[0][2]
        expect(request.variants).toHaveLength(20)
        const launchIds = request.variants.flatMap((variant) => variant.launch_ids)
        expect(launchIds).toHaveLength(20 * repeats)
        expect(logic.values.tracked.map((entry) => entry.launchId).sort()).toEqual([...launchIds].sort())

        logic.actions.trackLaunches(
            Array.from({ length: 100 }, (_, index) => ({
                configId: trialFixtureConfig.id,
                launchId: `other-trial-${index}`,
            }))
        )
        expect(logic.values.comparisonRows).toHaveLength(20 * repeats)
        expect(logic.values.tracked.filter((entry) => launchIds.includes(entry.launchId))).toHaveLength(20 * repeats)
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
        expect(request.expected_skill_version).toBe(trialFixtureSetup.skill_version)
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

        featureFlagLogic.actions.setFeatureFlags([], {})
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialComparisonCreate).toHaveBeenCalledTimes(1)
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], { [FEATURE_FLAGS.SCOUT_TRIALS]: true })

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
                error: 'The scout trial has not started. Retry the launch with the same ID.',
            })
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
            expect(logic.values.comparisonRows.every((row) => row.status === 'not_started')).toBe(true)
            expect(logic.values.comparisonRows.every((row) => row.error === null)).toBe(true)
            const launchId = logic.values.comparisonRows[0].launchId
            logic.actions.selectResult(launchId)
            expect(logic.values.selectedResult?.error).toBeNull()
            expect(logic.values.results[launchId].error).toContain('has not started')
            logic.actions.setResults({}, { [launchId]: 'Status unavailable.' })
            expect(logic.values.comparisonRows[0].error).toBe('Status unavailable.')
            logic.actions.setResults({ [launchId]: logic.values.results[launchId] }, {})
            const saved = logic.values.comparisonState.value!
            jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({
                results: [{ ...saved, status: 'not_started' }],
                has_more: false,
            })
            await expectLogic(logic, () =>
                logic.actions.loadComparisonHistory(trialFixtureConfig.id)
            ).toFinishAllListeners()
            expect(logic.values.comparisonState.value?.status).toBe(saved.status)
            expect(logic.values.selectedResult?.error).toBeNull()

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

    test.each(['not_started', 'failed', 'unknown'] as const)(
        'keeps launch errors actionable when the trial itself is %s',
        async (status) => {
            jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, params) => ({
                ...trialFixtureResult,
                launch_id: params.launch_id,
                status: 'not_started',
                task_status: null,
                error: 'The scout trial has not started. Retry the launch with the same ID.',
            }))
            await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
            const comparison = logic.values.comparisonState.value!
            const launchId = logic.values.comparisonRows[0].launchId
            logic.actions.selectResult(launchId)
            expect(logic.values.selectedResult?.error).toBeNull()

            jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue({ ...comparison, status })
            await expectLogic(logic, () =>
                logic.actions.loadComparison(comparison.comparison_id)
            ).toFinishAllListeners()

            expect(logic.values.comparisonRows[0].error).toContain('has not started')
            expect(logic.values.selectedResult?.error).toContain('has not started')
        }
    )

    test.each([
        ['failed', true],
        ['not_started', false],
    ] as const)('keeps run errors for status=%s and owned by an active trial=%s', async (status, owned) => {
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        const launchId = owned ? logic.values.comparisonRows[0].launchId : 'unrelated-launch'
        const result = { ...trialFixtureResult, launch_id: launchId, status, error: 'Run needs attention.' }
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId }])
        logic.actions.setResults({ [launchId]: result }, {})
        logic.actions.selectResult(launchId)

        expect(logic.values.rows.find((row) => row.launchId === launchId)?.error).toBe(result.error)
        expect(logic.values.selectedResult?.error).toBe(result.error)

        logic.actions.untrackLaunches([launchId])
        expect(logic.values.selectedResult?.error).toBe(result.error)
    })

    it('reuses completed results during background refresh and reloads them on explicit refresh', async () => {
        await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
        jest.mocked(signalsScoutConfigTrialResult).mockClear()

        await expectLogic(logic, () => logic.actions.refreshResults()).toFinishAllListeners()
        expect(signalsScoutConfigTrialResult).not.toHaveBeenCalled()

        await expectLogic(logic, () => logic.actions.refreshResults(true)).toFinishAllListeners()
        expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(2)
    })

    it('bounds concurrent result reads and preserves successful, failed, and missing launch results', async () => {
        const launches = Array.from({ length: 12 }, (_, index) => `launch-${index}`)
        const gate = promiseResolveReject<void>()
        let active = 0
        let maximumActive = 0
        jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, { launch_id }) => {
            active++
            maximumActive = Math.max(maximumActive, active)
            try {
                await gate.promise
                if (launch_id === launches[2]) {
                    throw new Error('Status unavailable')
                }
                if (launch_id === launches[7]) {
                    throw new ApiError('Not found', 404)
                }
                return { ...trialFixtureResult, launch_id }
            } finally {
                active--
            }
        })
        logic.actions.trackLaunches(launches.map((launchId) => ({ configId: trialFixtureConfig.id, launchId })))
        logic.actions.refreshResults()
        try {
            expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(5)
            expect(logic.values.refreshing).toBe(true)
        } finally {
            await expectLogic(logic, () => gate.resolve()).toFinishAllListeners()
        }

        expect(maximumActive).toBe(5)
        expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(12)
        expect(Object.keys(logic.values.results)).toEqual(launches.filter((_, index) => index !== 2 && index !== 7))
        expect(Object.keys(logic.values.resultErrors)).toEqual([launches[2]])
        expect(logic.values.tracked.map(({ launchId }) => launchId)).not.toContain(launches[7])
        expect(logic.values.refreshing).toBe(false)
    })

    it('stops queued result reads after unmounting', async () => {
        const gate = promiseResolveReject<void>()
        jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, { launch_id }) => {
            await gate.promise
            return { ...trialFixtureResult, launch_id }
        })
        logic.actions.trackLaunches(
            Array.from({ length: 12 }, (_, index) => ({ configId: trialFixtureConfig.id, launchId: `launch-${index}` }))
        )
        logic.actions.refreshResults()
        logic.unmount()
        try {
            await expectLogic(logic, () => gate.resolve()).toFinishAllListeners()
            expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(5)
        } finally {
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
        }
    })

    it.each([400, 503])('does not poll planned launches after a rejected or unconfirmed start (%s)', async (status) => {
        logic.unmount()
        jest.useFakeTimers()
        const visibility = jest.spyOn(document, 'hidden', 'get').mockReturnValue(false)
        try {
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            jest.mocked(signalsScoutConfigTrialComparisonCreate).mockRejectedValueOnce(
                new ApiError('Start failed', status)
            )
            await expectLogic(logic, () => logic.actions.submitComparison()).toFinishAllListeners()
            expect(logic.values.tracked).toEqual([])
            expect(signalsScoutConfigTrialResult).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(30_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(signalsScoutConfigTrialResult).not.toHaveBeenCalled()
            expect(logic.values.comparisonState.notStarted).toBe(true)
            expect(signalsScoutConfigTrialComparisonRetrieve).toHaveBeenCalledTimes(status === 400 ? 0 : 1)

            logic.unmount()
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            await jest.advanceTimersByTimeAsync(20_000)
            await expectLogic(logic).toFinishAllListeners()
            expect(signalsScoutConfigTrialResult).not.toHaveBeenCalled()
        } finally {
            visibility.mockRestore()
            jest.useRealTimers()
        }
    })

    it('stops polling a missing old launch until the server confirms it in history', async () => {
        const launchId = trialFixtureResult.launch_id
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId }])
        jest.mocked(signalsScoutConfigTrialResult).mockRejectedValueOnce(new ApiError('Not found', 404))
        await expectLogic(logic, () => logic.actions.refreshResults()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.refreshResults()).toFinishAllListeners()
        expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(1)
        expect(logic.values.tracked).toEqual([])

        await expectLogic(logic, () => {
            logic.actions.loadHistorySuccess({
                results: [
                    {
                        ...trialFixtureResult,
                        variant: 'Baseline',
                        started_at: trialFixtureResult.started_at!,
                        run_id: trialFixtureResult.run_id!,
                        task_id: trialFixtureResult.task_id!,
                        task_run_id: trialFixtureResult.task_run_id!,
                    },
                ],
                has_more: false,
            })
        }).toFinishAllListeners()
        expect(logic.values.results[launchId]).toEqual(trialFixtureResult)
        expect(logic.values.pollError).toBeNull()
    })

    it('fetches a completed run found in history while an earlier result is loading', async () => {
        let resolveOld!: (value: ScoutTrialResultApi) => void
        jest.mocked(signalsScoutConfigTrialResult).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    resolveOld = resolve
                })
        )
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId: trialFixtureResult.launch_id }])
        logic.actions.refreshResults()
        const newLaunch = '00000000-0000-4000-8000-000000000012'
        logic.actions.loadHistorySuccess({
            results: [
                {
                    ...trialFixtureResult,
                    launch_id: newLaunch,
                    variant: 'Saved run',
                    started_at: trialFixtureResult.started_at!,
                    run_id: trialFixtureResult.run_id!,
                    task_id: trialFixtureResult.task_id!,
                    task_run_id: trialFixtureResult.task_run_id!,
                },
            ],
            has_more: false,
        })
        await expectLogic(logic, () => resolveOld(trialFixtureResult)).toFinishAllListeners()
        expect(logic.values.results[newLaunch]?.launch_id).toBe(newLaunch)
        expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(2)
    })

    it('does not show an old scout result failure on the newly selected empty scout', async () => {
        let rejectOld!: (error: Error) => void
        jest.mocked(signalsScoutConfigTrialResult).mockImplementationOnce(
            () =>
                new Promise((_, reject) => {
                    rejectOld = reject
                })
        )
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId: trialFixtureResult.launch_id }])
        logic.actions.refreshResults()
        const newConfig = '00000000-0000-4000-8000-000000000010'
        jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue({ ...trialFixtureSetup, config_id: newConfig })
        await expectLogic(logic, () => logic.actions.selectConfig(newConfig)).toDispatchActions(['loadHistorySuccess'])
        await expectLogic(logic, () => rejectOld(new Error('Old result failed'))).toFinishAllListeners()
        expect(logic.values.rows).toEqual([])
        expect(logic.values.pollError).toBeNull()
    })

    it('clears recovered history errors without clearing a separate result error', async () => {
        jest.mocked(signalsScoutConfigTrialHistory).mockRejectedValueOnce(new Error('History failed'))
        await expectLogic(logic, () => logic.actions.loadHistory(trialFixtureConfig.id)).toFinishAllListeners()
        expect(logic.values.pollError).toContain("Couldn't load recent runs")
        await expectLogic(logic, () => logic.actions.loadHistory(trialFixtureConfig.id)).toFinishAllListeners()
        expect(logic.values.pollError).toBeNull()

        logic.actions.setPollError('Result request failed')
        jest.mocked(signalsScoutConfigTrialComparisonHistory).mockRejectedValueOnce(new Error('History failed'))
        await expectLogic(logic, () =>
            logic.actions.loadComparisonHistory(trialFixtureConfig.id)
        ).toFinishAllListeners()
        expect(logic.values.pollError).toContain("Couldn't load trial history")
        await expectLogic(logic, () =>
            logic.actions.loadComparisonHistory(trialFixtureConfig.id)
        ).toFinishAllListeners()
        expect(logic.values.pollError).toBe('Result request failed')
    })

    it.each(['loadSetup', 'loadHistory', 'loadComparisonHistory'] as const)(
        'ignores a late %s failure after selecting another scout',
        async (action) => {
            let rejectOld!: (error: Error) => void
            const request = {
                loadSetup: signalsScoutConfigTrialSetup,
                loadHistory: signalsScoutConfigTrialHistory,
                loadComparisonHistory: signalsScoutConfigTrialComparisonHistory,
            }[action]
            jest.mocked(request).mockImplementationOnce(
                () =>
                    new Promise<never>((_, reject) => {
                        rejectOld = reject
                    })
            )
            logic.actions[action](trialFixtureConfig.id)
            const newConfig = '00000000-0000-4000-8000-000000000010'
            jest.mocked(signalsScoutConfigTrialSetup).mockResolvedValue({ ...trialFixtureSetup, config_id: newConfig })
            await expectLogic(logic, () => logic.actions.selectConfig(newConfig)).toDispatchActions([
                'loadSetupSuccess',
                'loadHistorySuccess',
                'loadComparisonHistorySuccess',
            ])
            await expectLogic(logic, () => rejectOld(new Error('Old scout request failed'))).toFinishAllListeners()
            expect(logic.values.pageError).toBeNull()
            expect(logic.values.pollError).toBeNull()
            expect(logic.values.setup?.config_id).toBe(newConfig)
        }
    )

    it('retries the failed scout list with a selected scout and preserves edited versions', async () => {
        logic.actions.updateVariant('1', { label: 'My version', prompt: 'My draft', replacePrompt: true })
        const variants = logic.values.variants
        jest.mocked(signalsScoutConfigList).mockRejectedValueOnce(new Error('List failed'))
        await expectLogic(logic, () => logic.actions.loadConfigs()).toFinishAllListeners()
        logic.actions.loadSetupSuccess(trialFixtureSetup)
        expect(logic.values.pageError).toContain("Couldn't load scouts")
        logic.actions.setVariants(variants)
        jest.mocked(signalsScoutConfigList).mockClear()
        const firstConfig = {
            ...trialFixtureConfig,
            id: '00000000-0000-4000-8000-000000000010',
            skill_name: 'signals-scout-zebra',
            display_name: 'Account activity',
        }
        jest.mocked(signalsScoutConfigList).mockResolvedValue([trialFixtureConfig, firstConfig])
        jest.mocked(signalsScoutConfigTrialSetup).mockClear()
        await expectLogic(logic, () => logic.actions.retryPageLoad()).toFinishAllListeners()
        expect(signalsScoutConfigList).toHaveBeenCalledTimes(1)
        expect(signalsScoutConfigTrialSetup).not.toHaveBeenCalled()
        expect(logic.values.configs?.map((config) => config.id)).toEqual([firstConfig.id, trialFixtureConfig.id])
        expect(logic.values.selectedConfigId).toBe(trialFixtureConfig.id)
        expect(logic.values.variants).toEqual(variants)
        expect(logic.values.pageError).toBeNull()

        jest.mocked(signalsScoutConfigTrialSetup).mockRejectedValueOnce(new Error('Setup failed'))
        await expectLogic(logic, () => logic.actions.loadSetup(trialFixtureConfig.id)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.retryPageLoad()).toFinishAllListeners()
        expect(signalsScoutConfigList).toHaveBeenCalledTimes(1)
        expect(logic.values.pageError).toBeNull()
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
        const gate = promiseResolveReject<void>()
        jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, { launch_id }) => {
            await gate.promise
            return { ...trialFixtureResult, launch_id }
        })
        logic.actions.trackLaunches(
            Array.from({ length: 12 }, (_, index) => ({
                configId: trialFixtureConfig.id,
                launchId: `old-launch-${index}`,
            }))
        )
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
        await expectLogic(logic, () => gate.resolve()).toFinishAllListeners()

        expect(signalsScoutConfigTrialResult).toHaveBeenCalledTimes(6)
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

    test.each([true, false])(
        'keeps saved trials readable without paid submissions when the flag is %s',
        async (enabled) => {
            featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.SCOUT_TRIALS] : [], {
                [FEATURE_FLAGS.SCOUT_TRIALS]: enabled,
            })
            jest.mocked(signalsScoutConfigTrialComparisonHistory).mockResolvedValue({
                results: [trialFixtureServerComparison],
                has_more: false,
            })
            jest.mocked(signalsScoutConfigTrialComparisonRetrieve).mockResolvedValue(trialFixtureServerComparison)

            await expectLogic(logic, () =>
                logic.actions.loadComparisonHistory(trialFixtureConfig.id)
            ).toFinishAllListeners()

            expect(logic.values.selectedComparison?.id).toBe(trialFixtureServerComparison.comparison_id)
            expect(logic.values.trialView).toBe('list')
            expect(logic.values.evaluationState.value?.report).toEqual(trialFixtureServerComparison.evaluation?.report)
            expect(logic.values.comparisonRows).toHaveLength(4)
            expect(signalsScoutConfigTrialComparisonRetrieve).not.toHaveBeenCalled()

            await expectLogic(logic, () => logic.actions.newComparison()).toFinishAllListeners()
            expect(logic.values.trialView).toBe(enabled ? 'setup' : 'list')
            await expectLogic(logic, () => logic.actions.showTrialList()).toFinishAllListeners()
            expect(logic.values.trialView).toBe('list')
            expect(logic.values.comparisonsForConfig.map((trial) => trial.id)).toEqual([
                trialFixtureServerComparison.comparison_id,
            ])
            await expectLogic(logic, () =>
                logic.actions.selectComparison(trialFixtureConfig.id, trialFixtureServerComparison.comparison_id)
            ).toFinishAllListeners()
            expect(logic.values.trialView).toBe('detail')
            expect(logic.values.evaluationState.value?.report).toEqual(trialFixtureServerComparison.evaluation?.report)
            await expectLogic(logic, () => logic.actions.showTrialList()).toFinishAllListeners()
            expect(logic.values.trialView).toBe('list')
            expect(signalsScoutConfigTrialComparisonCreate).not.toHaveBeenCalled()
            expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
        }
    )

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

        featureFlagLogic.actions.setFeatureFlags([], {})
        await expectLogic(logic, () => logic.actions.resumeComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialComparisonResume).not.toHaveBeenCalled()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], { [FEATURE_FLAGS.SCOUT_TRIALS]: true })

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

        featureFlagLogic.actions.setFeatureFlags([], {})
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], { [FEATURE_FLAGS.SCOUT_TRIALS]: true })

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
                label: `Version ${index + 1}`,
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

            featureFlagLogic.actions.setFeatureFlags([], {})
            await expectLogic(logic, () => logic.actions.newScoringAttempt()).toFinishAllListeners()
            expect(logic.values.comparisons).toHaveLength(1)
            expect(logic.values.evaluationState.value?.report).toEqual(previousEvaluation.report)
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUT_TRIALS], {
                [FEATURE_FLAGS.SCOUT_TRIALS]: true,
            })

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

            jest.mocked(signalsScoutConfigTrialEvaluationRetrieve).mockImplementation(async (_, __, params) => {
                if (params.evaluation_id === previousEvaluation.evaluation_id) {
                    return previousEvaluation
                }
                throw new ApiError('Not found', 404)
            })
            expect(JSON.stringify(localStorage)).not.toContain(previousEvaluation.request.variants[0].label)
            logic.unmount()
            logic = scoutTrialsLogic({ teamId: 2, userId: 42 })
            await expectLogic(logic, () => {
                logic.mount()
            }).toFinishAllListeners()
            expect(logic.values.selectedComparison?.id).toBe(next.id)
            expect(logic.values.evaluationState.preparedRequest).toEqual({
                ...previousEvaluation.request,
                evaluation_id: next.id,
                rubric_source: 'saved',
            })
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
            rubric_source: 'saved' as const,
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

    it('blocks a restored scoring attempt if its exact original request cannot be loaded', async () => {
        const comparison = { ...trialFixtureComparison, sourceEvaluationId: '00000000-0000-4000-8000-000000000098' }
        logic.actions.registerComparison(comparison)
        await expectLogic(logic, () =>
            logic.actions.selectComparison(comparison.configId, comparison.id)
        ).toFinishAllListeners()
        expect(logic.values.evaluationState.error).toContain('Scoring status could not be loaded')
        expect(logic.values.scoreDisabledReason).not.toBeNull()
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(signalsScoutConfigTrialEvaluationCreate).not.toHaveBeenCalled()
    })

    it.each([
        ['Save a reviewed rubric before scoring this comparison.', 400],
        ['Generate suggestions, adopt their reference, and save the rubric before scoring.', 400],
        ['This project has reached its daily scout run budget. Try again later.', 429],
        ['This project has reached its daily report limit.', 403],
    ])('shows the server reason for a rejected score and allows an explicit retry: %s', async (message, status) => {
        logic.actions.registerComparison(trialFixtureComparison)
        await expectLogic(logic, () =>
            logic.actions.selectComparison(trialFixtureComparison.configId, trialFixtureComparison.id)
        ).toFinishAllListeners()
        jest.mocked(signalsScoutConfigTrialEvaluationCreate).mockRejectedValueOnce(new ApiError(message, status))
        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(logic.values.evaluationState.error).toBe(message)
        expect(logic.values.evaluationState.notStarted).toBe(true)
        expect(logic.values.scoreDisabledReason).toBeNull()
        const request = jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[0][2]

        await expectLogic(logic, () => logic.actions.scoreComparison()).toFinishAllListeners()
        expect(jest.mocked(signalsScoutConfigTrialEvaluationCreate).mock.calls[1][2]).toEqual(request)
    })

    it('keeps a failed stop on its run so the retry stops the run instead of reloading setup', async () => {
        const launchId = trialFixtureResult.launch_id
        let stopped = false
        jest.mocked(signalsScoutConfigTrialResult).mockImplementation(async (_, __, params) => ({
            ...trialFixtureResult,
            launch_id: params.launch_id,
            status: stopped ? 'cancelled' : 'running',
            task_status: stopped ? 'cancelled' : 'in_progress',
        }))
        logic.actions.trackLaunches([{ configId: trialFixtureConfig.id, launchId }])
        await expectLogic(logic, () => logic.actions.refreshResults(true)).toFinishAllListeners()
        const rowError = (): string | null | undefined =>
            logic.values.rows.find((row) => row.launchId === launchId)?.error
        jest.mocked(tasksRunsCancelCreate).mockRejectedValueOnce(new Error('Connection closed'))

        await expectLogic(logic, () => logic.actions.cancelRun(launchId)).toFinishAllListeners()
        expect(logic.values.pageError).toBeNull()
        expect(rowError()).toBe("Couldn't stop this run. Try again.")

        jest.mocked(tasksRunsCancelCreate).mockImplementationOnce(async () => {
            stopped = true
            return {} as Awaited<ReturnType<typeof tasksRunsCancelCreate>>
        })
        await expectLogic(logic, () => logic.actions.cancelRun(launchId)).toFinishAllListeners()
        expect(tasksRunsCancelCreate).toHaveBeenCalledTimes(2)
        expect(rowError()).toBeNull()
    })
})
