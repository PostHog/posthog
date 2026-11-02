import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesSummaryRegenerateCreate, errorTrackingIssuesSummaryRetrieve } from '../../generated/api'
import type {
    ErrorTrackingStoredIssueSummaryApi,
    ErrorTrackingIssueSummaryResponseApi,
} from '../../generated/api.schemas'
import { ISSUE_SUMMARY_POLL_INTERVAL_MS, ISSUE_SUMMARY_POLL_TIMEOUT_MS, issueSummaryLogic } from './issueSummaryLogic'

jest.mock('../../generated/api')

const ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'
const SUMMARY: ErrorTrackingStoredIssueSummaryApi = {
    what_happened: 'A TypeError in checkout.',
    likely_cause: 'The cart is null after a session expires.',
    who_is_affected: 'Signed-in users on Safari.',
    suggested_next_step: 'Guard the null cart.',
    category: 'own_code',
    model: 'gpt-4.1-mini',
    generated_at: '2026-10-20T12:00:00Z',
    checked_at: '2026-10-20T12:00:00Z',
}
const GENERATING: ErrorTrackingIssueSummaryResponseApi = { status: 'generating', summary: null }
const READY: ErrorTrackingIssueSummaryResponseApi = { status: 'ready', summary: SUMMARY }
const UNAVAILABLE: ErrorTrackingIssueSummaryResponseApi = { status: 'unavailable', summary: null }
const NEW_SUMMARY: ErrorTrackingStoredIssueSummaryApi = { ...SUMMARY, generated_at: '2026-10-22T12:00:00Z' }

describe('issueSummaryLogic', () => {
    const retrieve = jest.mocked(errorTrackingIssuesSummaryRetrieve)
    const regenerate = jest.mocked(errorTrackingIssuesSummaryRegenerateCreate)
    let logic: ReturnType<typeof issueSummaryLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.resetAllMocks()
    })

    async function advance(ms: number): Promise<void> {
        await jest.advanceTimersByTimeAsync(ms)
    }

    it.each([
        ['generation outlasts the deadline', GENERATING, 0, 'generating', 'timed_out'],
        ['a poll answers after the deadline', GENERATING, 1500, 'generating', 'timed_out'],
        ['no summary will be written', UNAVAILABLE, 0, 'hidden', 'hidden'],
    ])('stops polling when %s', async (_name, response, latencyMs, viewOnLoad, viewAtDeadline) => {
        retrieve.mockImplementation(() => new Promise((resolve) => setTimeout(() => resolve(response), latencyMs)))
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()
        await advance(latencyMs)
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess']).toMatchValues({ view: viewOnLoad })

        await advance(ISSUE_SUMMARY_POLL_TIMEOUT_MS + latencyMs)
        const callsAtDeadline = retrieve.mock.calls.length
        expect(logic.values.view).toBe(viewAtDeadline)

        await advance(ISSUE_SUMMARY_POLL_TIMEOUT_MS)
        expect(retrieve.mock.calls.length).toBe(callsAtDeadline)
    })

    it('stops polling once the summary is ready', async () => {
        retrieve.mockResolvedValueOnce(GENERATING).mockResolvedValueOnce(GENERATING).mockResolvedValue(READY)
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()

        await advance(ISSUE_SUMMARY_POLL_INTERVAL_MS * 2)
        expect(logic.values.view).toBe('ready')
        expect(logic.values.summary).toEqual(SUMMARY)

        await advance(ISSUE_SUMMARY_POLL_TIMEOUT_MS)
        expect(retrieve).toHaveBeenCalledTimes(3)
        expect(logic.values.view).toBe('ready')
    })

    it('stops polling on a failed read and recovers on retry', async () => {
        retrieve.mockResolvedValueOnce(GENERATING).mockRejectedValueOnce(new Error('500')).mockResolvedValue(READY)
        jest.spyOn(console, 'error').mockImplementation(() => {})
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()

        await advance(ISSUE_SUMMARY_POLL_INTERVAL_MS)
        expect(logic.values.view).toBe('failed')
        await advance(ISSUE_SUMMARY_POLL_TIMEOUT_MS)
        expect(retrieve).toHaveBeenCalledTimes(2)

        logic.actions.loadSummary()
        await advance(0)
        expect(logic.values.view).toBe('ready')
    })

    it.each([
        ['shows the new summary once it lands', [READY, { status: 'ready', summary: NEW_SUMMARY }], NEW_SUMMARY, false],
        ['tells the user when no new summary lands', [READY], SUMMARY, true],
    ] as const)('regenerate %s', async (_name, reads, expectedSummary, toasts) => {
        const info = jest.spyOn(lemonToast, 'info').mockImplementation(() => '')
        retrieve.mockResolvedValueOnce(READY)
        for (const read of reads.slice(0, -1)) {
            retrieve.mockResolvedValueOnce(read)
        }
        retrieve.mockResolvedValue(reads[reads.length - 1])
        regenerate.mockResolvedValue({ status: 'generating', summary: SUMMARY })
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])

        logic.actions.regenerateSummary()
        await advance(ISSUE_SUMMARY_POLL_INTERVAL_MS)
        expect(logic.values.regenerating).toBe(true)

        await advance(ISSUE_SUMMARY_POLL_TIMEOUT_MS)
        expect(logic.values.regenerating).toBe(false)
        expect(logic.values.summary).toEqual(expectedSummary)
        expect(info).toHaveBeenCalledTimes(toasts ? 1 : 0)
    })
})
