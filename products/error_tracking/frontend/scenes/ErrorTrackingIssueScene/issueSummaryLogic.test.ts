import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesSummaryRetrieve } from '../../generated/api'
import type { ErrorTrackingIssueSummaryApi, ErrorTrackingIssueSummaryResponseApi } from '../../generated/api.schemas'
import { ISSUE_SUMMARY_POLL_INTERVAL_MS, ISSUE_SUMMARY_POLL_TIMEOUT_MS, issueSummaryLogic } from './issueSummaryLogic'

jest.mock('../../generated/api')

const ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'
const SUMMARY: ErrorTrackingIssueSummaryApi = {
    what_happened: 'A TypeError in checkout.',
    likely_cause: 'The cart is null after a session expires.',
    who_is_affected: 'Signed-in users on Safari.',
    suggested_next_step: 'Guard the null cart.',
    category: 'own_code',
    model: 'gpt-4.1-mini',
    generated_at: '2026-10-20T12:00:00Z',
}
const GENERATING: ErrorTrackingIssueSummaryResponseApi = { status: 'generating', summary: null }
const READY: ErrorTrackingIssueSummaryResponseApi = { status: 'ready', summary: SUMMARY }

describe('issueSummaryLogic', () => {
    const retrieve = jest.mocked(errorTrackingIssuesSummaryRetrieve)
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

    it('stops polling and offers a retry when generation outlasts the deadline', async () => {
        retrieve.mockResolvedValue(GENERATING)
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess']).toMatchValues({ view: 'generating' })

        await advance(ISSUE_SUMMARY_POLL_TIMEOUT_MS)
        const callsAtDeadline = retrieve.mock.calls.length
        expect(logic.values.view).toBe('timed_out')

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
})
