import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { errorTrackingIssuesSummarizeCreate, errorTrackingIssuesSummaryRetrieve } from '../../generated/api'
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
    model: 'gpt-6-luna',
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
const SETTING_OFF: ErrorTrackingIssueSummaryResponseApi = {
    status: 'unavailable',
    summary: null,
    reason: 'setting_off',
}

function refusal(status: number, code: string): ApiError {
    return new ApiError('Request failed', status, undefined, { code, detail: 'No summary was written.' })
}

describe('issueSummaryLogic', () => {
    const retrieve = jest.mocked(errorTrackingIssuesSummaryRetrieve)
    const summarize = jest.mocked(errorTrackingIssuesSummarizeCreate)
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
        ['the project has not turned summaries on', SETTING_OFF, null, 'hidden'],
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
            expect(summarize).not.toHaveBeenCalled()
        }
    )

    it.each([
        ['the summary is written', () => summarize.mockResolvedValue(READY), 'ready'],
        [
            'the organization is out of AI credits',
            () => summarize.mockRejectedValue(refusal(402, 'out_of_credits')),
            'out_of_credits',
        ],
        [
            'the project asked too often',
            () => summarize.mockRejectedValue(refusal(429, 'rate_limited')),
            'rate_limited',
        ],
        [
            'another request is writing it',
            () => summarize.mockRejectedValue(refusal(409, 'in_progress')),
            'in_progress',
        ],
        [
            'summaries are off for the project',
            () => summarize.mockRejectedValue(refusal(403, 'setting_off')),
            'setting_off',
        ],
        ['the model call fails', () => summarize.mockRejectedValue(refusal(503, 'failed')), 'summarize_failed'],
        [
            'the token lacks the write scope',
            () => summarize.mockRejectedValue(refusal(403, 'permission_denied')),
            'summarize_failed',
        ],
        ['the network fails', () => summarize.mockRejectedValue(new Error('offline')), 'summarize_failed'],
    ])('shows the outcome of a summarize click when %s', async (_name, arrange, view) => {
        retrieve.mockResolvedValue(NOT_GENERATED)
        arrange()
        jest.spyOn(console, 'error').mockImplementation(() => {})
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess']).toMatchValues({ view: 'not_generated' })

        logic.actions.summarize()

        await expectLogic(logic).toDispatchActions(['summarizeSuccess']).toMatchValues({ view })
        expect(summarize).toHaveBeenCalledTimes(1)
    })

    it('holds the button in a loading state until the summary arrives, and reports the request and the view', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        retrieve.mockResolvedValue(NOT_GENERATED)
        let resolveSummarize: (response: ErrorTrackingIssueSummaryResponseApi) => void = () => {}
        summarize.mockReturnValue(new Promise((resolve) => (resolveSummarize = resolve)))
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])

        logic.actions.summarize()
        expect(logic.values.summaryResponseLoading).toBe(true)
        expect(capture).toHaveBeenCalledWith('error_tracking_issue_summary_requested', { issue_id: ISSUE_ID })

        resolveSummarize(READY)
        await expectLogic(logic).toDispatchActions(['summarizeSuccess']).toMatchValues({
            view: 'ready',
            summaryResponseLoading: false,
        })
        expect(capture).toHaveBeenCalledWith(
            'error_tracking_issue_summary_viewed',
            expect.objectContaining({ issue_id: ISSUE_ID, generated_at: SUMMARY.generated_at })
        )
    })

    it('offers the summarize button again when a check after in_progress finds no summary', async () => {
        retrieve.mockResolvedValue(NOT_GENERATED)
        summarize.mockRejectedValue(refusal(409, 'in_progress'))
        jest.spyOn(console, 'error').mockImplementation(() => {})
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])
        logic.actions.summarize()
        await expectLogic(logic).toDispatchActions(['summarizeSuccess']).toMatchValues({ view: 'in_progress' })

        logic.actions.loadSummary()

        await expectLogic(logic).toDispatchActions(['loadSummarySuccess']).toMatchValues({ view: 'not_generated' })
    })

    it('keeps the refusal on screen while a retry runs', async () => {
        retrieve.mockResolvedValue(NOT_GENERATED)
        jest.spyOn(console, 'error').mockImplementation(() => {})
        summarize.mockRejectedValueOnce(refusal(429, 'rate_limited'))
        let resolveRetry: (response: ErrorTrackingIssueSummaryResponseApi) => void = () => {}
        summarize.mockReturnValueOnce(new Promise((resolve) => (resolveRetry = resolve)))
        logic = issueSummaryLogic({ issueId: ISSUE_ID, firstSeen: null })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSummarySuccess'])
        logic.actions.summarize()
        await expectLogic(logic).toDispatchActions(['summarizeSuccess']).toMatchValues({ view: 'rate_limited' })

        logic.actions.summarize()
        expect(logic.values).toMatchObject({ view: 'rate_limited', summaryResponseLoading: true })

        resolveRetry(READY)
        await expectLogic(logic).toDispatchActions(['summarizeSuccess']).toMatchValues({ view: 'ready' })
    })

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
