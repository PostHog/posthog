import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { initKeaTests } from '~/test/init'

import { llmAnalyticsReviewsLogic } from './llmAnalyticsReviewsLogic'
import { traceReviewsApi } from './traceReviewsApi'
import { CLIPBOARD_ROW_LIMIT } from './traceReviewsExport'
import type { TraceReview } from './types'

jest.mock('lib/utils/copyToClipboard')
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
        warning: jest.fn(),
    },
}))
jest.mock('./traceReviewsApi', () => ({
    ...jest.requireActual('./traceReviewsApi'),
    traceReviewsApi: {
        list: jest.fn(),
    },
}))
jest.mock('../generated/api', () => ({
    llmAnalyticsScoreDefinitionsList: jest
        .fn()
        .mockResolvedValue({ results: [], count: 0, next: null, previous: null }),
}))

const mockTraceReviewsList = traceReviewsApi.list as jest.MockedFunction<typeof traceReviewsApi.list>
const mockCopyToClipboard = copyToClipboard as jest.MockedFunction<typeof copyToClipboard>
const mockLemonToastError = lemonToast.error as jest.MockedFunction<typeof lemonToast.error>
const mockLemonToastWarning = lemonToast.warning as jest.MockedFunction<typeof lemonToast.warning>

const baseReview: TraceReview = {
    id: 'review-1',
    trace_id: 'trace-abc',
    trace_url: 'https://us.posthog.com/project/1/llm-analytics/traces/trace-abc',
    comment: 'Looks good',
    created_at: '2026-03-12T00:00:00Z',
    updated_at: '2026-03-12T01:00:00Z',
    created_by: null,
    reviewed_by: null,
    scores: [],
    team: 1,
}

describe('llmAnalyticsReviewsLogic.copyReviewsToClipboard', () => {
    let logic: ReturnType<typeof llmAnalyticsReviewsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        logic = llmAnalyticsReviewsLogic({ tabId: 'test-tab' })
        // Stub the initial mount load so afterMount doesn't interfere with our test mocks.
        mockTraceReviewsList.mockResolvedValue({ results: [], count: 0 })
        logic.mount()
    })

    it('copies the formatted payload to the clipboard on the happy path', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockResolvedValueOnce({ results: [baseReview], count: 1 })

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)
        expect(mockCopyToClipboard.mock.calls[0][1]).toBe('reviews')
    })

    it('shows an error toast and skips the clipboard write when there are no reviews', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockResolvedValueOnce({ results: [], count: 0 })

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockLemonToastError).toHaveBeenCalledWith('No reviews to copy!')
        expect(mockCopyToClipboard).not.toHaveBeenCalled()
    })

    it('shows a warning pointing at the file export when the dataset exceeds the cap', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockResolvedValueOnce({
            results: [baseReview],
            count: CLIPBOARD_ROW_LIMIT + 1,
        })

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockLemonToastWarning).toHaveBeenCalledTimes(1)
        const message = mockLemonToastWarning.mock.calls[0][0] as string
        expect(message).toContain(String(CLIPBOARD_ROW_LIMIT + 1))
        expect(message).toContain('Export current columns')
        expect(mockCopyToClipboard).not.toHaveBeenCalled()
    })

    it('falls back to an error toast when the fetch fails', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockRejectedValueOnce(new Error('network down'))

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
    })

    it('cancels an earlier invocation when called twice in quick succession', async () => {
        mockTraceReviewsList.mockReset()
        let resolveFirst: ((value: { results: TraceReview[]; count: number }) => void) | undefined
        mockTraceReviewsList
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveFirst = resolve
                    })
            )
            .mockResolvedValueOnce({ results: [baseReview], count: 1 })

        // Click 1 hangs on the API; click 2 resolves immediately and should win.
        logic.actions.copyReviewsToClipboard('csv')
        logic.actions.copyReviewsToClipboard('csv')

        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))
        await flush()
        await flush()

        // Click 2 has finished and written to the clipboard.
        expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)

        // Now unblock click 1: when it resumes, breakpoint() should detect the newer
        // invocation and throw, so no second clipboard write happens.
        resolveFirst?.({ results: [baseReview], count: 1 })
        await flush()
        await flush()

        expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)
    })
})
