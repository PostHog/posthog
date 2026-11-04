import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesSummaryRetrieve } from '../../generated/api'
import type {
    ErrorTrackingStoredIssueSummaryApi,
    ErrorTrackingIssueSummaryResponseApi,
} from '../../generated/api.schemas'
import { issuePaneSectionsLogic } from './issuePaneSectionsLogic'
import { issueSummaryLogic } from './issueSummaryLogic'

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
const READY: ErrorTrackingIssueSummaryResponseApi = { status: 'ready', summary: SUMMARY, reason: null }
const NOT_GENERATED: ErrorTrackingIssueSummaryResponseApi = { status: 'not_generated', summary: null, reason: null }
const UNAVAILABLE: ErrorTrackingIssueSummaryResponseApi = { status: 'unavailable', summary: null, reason: 'disabled' }
const AI_NOT_APPROVED: ErrorTrackingIssueSummaryResponseApi = {
    status: 'unavailable',
    summary: null,
    reason: 'ai_not_approved',
}
const RESTRICTED: ErrorTrackingIssueSummaryResponseApi = { status: 'unavailable', summary: null, reason: 'restricted' }

describe('issueSummaryLogic', () => {
    const retrieve = jest.mocked(errorTrackingIssuesSummaryRetrieve)
    let logic: ReturnType<typeof issueSummaryLogic.build>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-11-04T12:00:00Z'))
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        localStorage.clear()
        jest.useRealTimers()
        jest.resetAllMocks()
    })

    async function advance(ms: number): Promise<void> {
        await jest.advanceTimersByTimeAsync(ms)
    }

    it.each([
        ['a summary is stored', READY, null, 'ready'],
        ['no summary is stored for an older issue', NOT_GENERATED, '2026-11-04T11:00:00Z', 'not_generated'],
        ['no summary is stored yet for a new issue', NOT_GENERATED, '2026-11-04T11:59:00Z', 'writing'],
        ['summaries are off for the project', UNAVAILABLE, null, 'hidden'],
        ['the organization has not approved AI', AI_NOT_APPROVED, null, 'ai_not_approved'],
        ['the person cannot read the summary sources', RESTRICTED, null, 'restricted'],
    ])(
        'shows nothing before the answer, then reads once and never polls when %s',
        async (_name, response, firstSeen, view) => {
            retrieve.mockResolvedValue(response)
            logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen })
            logic.mount()
            expect(logic.values.view).toBe('hidden')

            await expectLogic(logic).toDispatchActions(['loadSummarySuccess']).toMatchValues({ view })
            await advance(60_000)
            expect(retrieve).toHaveBeenCalledTimes(1)
        }
    )

    it('shows nothing when the first read fails, and recovers on retry', async () => {
        retrieve.mockRejectedValueOnce(new Error('500')).mockResolvedValue(READY)
        jest.spyOn(console, 'error').mockImplementation(() => {})
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()

        await advance(0)
        expect(logic.values.view).toBe('hidden')
        expect(retrieve).toHaveBeenCalledTimes(1)

        logic.actions.loadSummary()
        await advance(0)
        expect(logic.values.view).toBe('ready')
    })

    it('shows a failed check once an earlier read said summaries are on', async () => {
        retrieve.mockResolvedValueOnce(NOT_GENERATED).mockRejectedValueOnce(new Error('500'))
        jest.spyOn(console, 'error').mockImplementation(() => {})
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()

        await advance(0)
        expect(logic.values.view).toBe('not_generated')

        logic.actions.loadSummary()
        await advance(0)
        expect(logic.values.view).toBe('failed')
    })

    it('reports whether the summary was open when viewed, and sends the rating', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        retrieve.mockResolvedValue(READY)
        issuePaneSectionsLogic.mount()
        issuePaneSectionsLogic.actions.setSummaryOpen(true)
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])
        logic.actions.sendFeedback('bad')

        expect(capture).toHaveBeenCalledWith(
            'error_tracking_issue_summary_viewed',
            expect.objectContaining({ issue_id: ISSUE_ID, summary_open: true })
        )
        expect(capture).toHaveBeenCalledWith(
            'error_tracking_issue_summary_feedback',
            expect.objectContaining({ issue_id: ISSUE_ID, feedback: 'bad', generated_at: SUMMARY.generated_at })
        )
    })
})
