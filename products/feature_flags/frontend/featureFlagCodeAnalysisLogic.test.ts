import { ApiError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { featureFlagCodeAnalysisLogic } from './featureFlagCodeAnalysisLogic'
import {
    featureFlagsAnalyzeCodeCreate,
    featureFlagsCodeAnalysisRetrieve,
    featureFlagsCodeAnalysisTargetRetrieve,
} from './generated/api'
import type { FeatureFlagCodeAnalysisApi } from './generated/api.schemas'

jest.mock('./generated/api', () => ({
    featureFlagsAnalyzeCodeCreate: jest.fn(),
    featureFlagsCodeAnalysisRetrieve: jest.fn(),
    featureFlagsCodeAnalysisTargetRetrieve: jest.fn(),
}))

const mockStart = featureFlagsAnalyzeCodeCreate as jest.Mock
const mockRetrieve = featureFlagsCodeAnalysisRetrieve as jest.Mock
const mockTarget = featureFlagsCodeAnalysisTargetRetrieve as jest.Mock

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
    ...overrides,
})

const completed = analysis({
    run_status: 'completed',
    is_terminal: true,
    result: { repository: 'example-org/example-repo', commit_sha: 'abc1234', references: [], notes: '' },
})

describe('featureFlagCodeAnalysisLogic', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        mockStart.mockReset()
        mockRetrieve.mockReset()
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
})
