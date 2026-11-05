import { ApiError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { featureFlagCodeAnalysisLogic } from './featureFlagCodeAnalysisLogic'
import {
    featureFlagsAnalyzeCodeCreate,
    featureFlagsCodeAnalysisRetrieve,
    featureFlagsCodeAnalysisTargetRetrieve,
    featureFlagsOpenCleanupPrCreate,
} from './generated/api'
import type { FeatureFlagCodeAnalysisApi, FeatureFlagCodeCleanupRunApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    featureFlagsAnalyzeCodeCreate: jest.fn(),
    featureFlagsCodeAnalysisRetrieve: jest.fn(),
    featureFlagsCodeAnalysisTargetRetrieve: jest.fn(),
    featureFlagsOpenCleanupPrCreate: jest.fn(),
}))

const mockStart = featureFlagsAnalyzeCodeCreate as jest.Mock
const mockRetrieve = featureFlagsCodeAnalysisRetrieve as jest.Mock
const mockTarget = featureFlagsCodeAnalysisTargetRetrieve as jest.Mock
const mockOpenCleanup = featureFlagsOpenCleanupPrCreate as jest.Mock

const POLL_INTERVAL_MS = 5000

const analysis = (overrides: Partial<FeatureFlagCodeAnalysisApi> = {}): FeatureFlagCodeAnalysisApi => ({
    task_id: 'task-1',
    repository: 'example-org/example-repo',
    created_at: '2026-01-01T00:00:00Z',
    run_status: 'in_progress',
    is_terminal: false,
    error_message: null,
    can_view_task: true,
    result: null,
    cleanup: { unavailable_reason: 'analysis_not_ready', suggested_outcome: null, outcome_options: [], run: null },
    ...overrides,
})

const completed = analysis({
    run_status: 'completed',
    is_terminal: true,
    result: { repository: 'example-org/example-repo', commit_sha: 'abc1234', references: [], notes: '' },
})

const cleanupRun = (overrides: Partial<FeatureFlagCodeCleanupRunApi> = {}): FeatureFlagCodeCleanupRunApi => ({
    task_id: 'cleanup-task-1',
    run_status: 'in_progress',
    is_terminal: false,
    pr_url: null,
    error_message: null,
    can_view_task: true,
    ...overrides,
})

const staleWithCleanup = (run: FeatureFlagCodeCleanupRunApi | null): FeatureFlagCodeAnalysisApi => ({
    ...completed,
    cleanup: { unavailable_reason: null, suggested_outcome: 'enabled', outcome_options: ['enabled', 'disabled'], run },
})

describe('featureFlagCodeAnalysisLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        mockStart.mockReset()
        mockRetrieve.mockReset()
        mockOpenCleanup.mockReset()
        mockTarget.mockReset().mockResolvedValue({
            repository: 'example-org/example-repo',
            source: 'single_repo',
            candidates: ['example-org/example-repo'],
        })
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.useRealTimers()
    })

    it('polls a running analysis until it is terminal, then stops', async () => {
        mockRetrieve.mockResolvedValueOnce(analysis()).mockResolvedValue(completed)

        const logic = featureFlagCodeAnalysisLogic({ id: 1 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.isRunning).toBe(true)

        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
        expect(mockRetrieve).toHaveBeenCalledTimes(2)
        expect(logic.values.analysis?.result?.commit_sha).toBe('abc1234')

        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 10)
        expect(mockRetrieve).toHaveBeenCalledTimes(2)
    })

    it('offers a manual check after polling keeps failing, and resumes polling once it succeeds', async () => {
        silenceKeaLoadersErrors()
        mockRetrieve
            .mockResolvedValueOnce(analysis())
            .mockRejectedValueOnce(new ApiError('Server error', 500))
            .mockRejectedValueOnce(new ApiError('Server error', 500))
            .mockRejectedValueOnce(new ApiError('Server error', 500))
            .mockResolvedValueOnce(analysis())
            .mockResolvedValue(completed)

        const logic = featureFlagCodeAnalysisLogic({ id: 1 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)
        expect(logic.values).toMatchObject({ pollingStopped: true, isRunning: true })

        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 10)
        expect(mockRetrieve).toHaveBeenCalledTimes(4)

        logic.actions.loadAnalysis()
        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
        expect(logic.values).toMatchObject({ pollingStopped: false, isRunning: false })
    })

    it('treats a flag that was never analyzed as empty, not as a load error', async () => {
        silenceKeaLoadersErrors()
        mockRetrieve.mockRejectedValue(new ApiError('Not found', 404))

        const logic = featureFlagCodeAnalysisLogic({ id: 1 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values).toMatchObject({ analysisLoaded: true, analysis: null, analysisLoadError: null })
    })

    it('follows the analysis already running when starting one conflicts', async () => {
        silenceKeaLoadersErrors()
        mockRetrieve
            .mockRejectedValueOnce(new ApiError('Not found', 404))
            .mockResolvedValueOnce(analysis())
            .mockResolvedValue(completed)
        mockStart.mockRejectedValue(new ApiError('An analysis is already running', 409))

        const logic = featureFlagCodeAnalysisLogic({ id: 1 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        logic.actions.startAnalysis()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values).toMatchObject({ startError: null, startingAnalysis: false, isRunning: true })

        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
        expect(logic.values.analysis?.is_terminal).toBe(true)
    })

    it('opens a cleanup PR for the suggested outcome and polls its run until it finishes', async () => {
        mockRetrieve
            .mockResolvedValueOnce(staleWithCleanup(null))
            .mockResolvedValue(
                staleWithCleanup(
                    cleanupRun({ run_status: 'completed', is_terminal: true, pr_url: 'https://github.com/o/r/pull/1' })
                )
            )
        mockOpenCleanup.mockResolvedValue(staleWithCleanup(cleanupRun()))

        const logic = featureFlagCodeAnalysisLogic({ id: 1 })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        logic.actions.openCleanupPr()
        await jest.advanceTimersByTimeAsync(0)
        expect(mockOpenCleanup).toHaveBeenCalledWith(expect.any(String), 1, { keep_outcome: 'enabled' })
        expect(logic.values.isCleanupRunning).toBe(true)

        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
        expect(logic.values.analysis?.cleanup.run?.pr_url).toBe('https://github.com/o/r/pull/1')

        await jest.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 10)
        expect(mockRetrieve).toHaveBeenCalledTimes(2)
    })
})
