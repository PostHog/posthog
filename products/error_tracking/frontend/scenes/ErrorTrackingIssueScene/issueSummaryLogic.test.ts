import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesSummaryRetrieve } from '../../generated/api'
import type {
    ErrorTrackingStoredIssueSummaryApi,
    ErrorTrackingIssueSummaryResponseApi,
} from '../../generated/api.schemas'
import { issueSummaryLogic } from './issueSummaryLogic'

jest.mock('../../generated/api')

const ISSUE_ID = '01890a1b-2c3d-4e4f-8a9b-0c1d2e3f4a5b'
const SUMMARY: ErrorTrackingStoredIssueSummaryApi = {
    what_happened: 'A TypeError in checkout.',
    likely_cause: 'The cart is null after a session expires.',
    who_is_affected: 'Signed-in users on Safari.',
    suggested_next_step: 'Guard the null cart.',
    model: 'gpt-4.1-mini',
    generated_at: '2026-10-20T12:00:00Z',
    checked_at: '2026-10-20T12:00:00Z',
}
const READY: ErrorTrackingIssueSummaryResponseApi = { status: 'ready', summary: SUMMARY, reason: null }
const NOT_GENERATED: ErrorTrackingIssueSummaryResponseApi = { status: 'not_generated', summary: null, reason: null }
const UNAVAILABLE: ErrorTrackingIssueSummaryResponseApi = { status: 'unavailable', summary: null, reason: 'disabled' }

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

    it.each([
        ['a summary is stored', READY, 'ready'],
        ['no summary is stored', NOT_GENERATED, 'hidden'],
        ['summaries are unavailable', UNAVAILABLE, 'hidden'],
    ])('reads once and never polls when %s', async (_name, response, view) => {
        retrieve.mockResolvedValue(response)
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSummarySuccess']).toMatchValues({ view })
        await advance(60_000)
        expect(retrieve).toHaveBeenCalledTimes(1)
    })

    it('shows a failed read and recovers on retry', async () => {
        retrieve.mockRejectedValueOnce(new Error('500')).mockResolvedValue(READY)
        jest.spyOn(console, 'error').mockImplementation(() => {})
        logic = issueSummaryLogic({ issueId: ISSUE_ID })
        logic.mount()

        await advance(0)
        expect(logic.values.view).toBe('failed')
        expect(retrieve).toHaveBeenCalledTimes(1)

        logic.actions.loadSummary()
        await advance(0)
        expect(logic.values.view).toBe('ready')
    })
})
