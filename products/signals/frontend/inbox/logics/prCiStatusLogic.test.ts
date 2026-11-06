/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PR_CI_STATUS_MAX_AGE_MS, PR_CI_STATUS_MAX_REPORTS, prCiStatusLogic } from './prCiStatusLogic'

const CI_STATUSES_URL = '/api/projects/:team_id/signals/reports/pr_ci_statuses/'

describe('prCiStatusLogic', () => {
    let logic: ReturnType<typeof prCiStatusLogic.build>
    let requestedIds: string[][]
    let answers: Record<string, string>

    beforeEach(() => {
        requestedIds = []
        answers = { 'report-1': 'failing', 'report-2': 'passing' }
        useMocks({
            get: {
                [CI_STATUSES_URL]: ({ request }) => {
                    const ids = (new URL(request.url).searchParams.get('report_ids') ?? '').split(',')
                    requestedIds.push(ids)
                    return [
                        200,
                        {
                            statuses: ids
                                .filter((id) => id in answers)
                                .map((id) => ({ report_id: id, ci_status: answers[id] })),
                        },
                    ]
                },
            },
        })
        initKeaTests()
        logic = prCiStatusLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('resolves every report the sections announce in one request', async () => {
        logic.actions.trackReports('needs-decision', ['report-1'])
        logic.actions.trackReports('monitoring', ['report-2'])
        await expectLogic(logic).toFinishAllListeners()

        // Two sections announcing separately still cost one round trip, which is what makes a glyph
        // on every row affordable.
        expect(requestedIds).toEqual([['report-1', 'report-2']])
        expect(logic.values.ciStatusByReportId).toEqual({ 'report-1': 'failing', 'report-2': 'passing' })
    })

    it('covers every tracked report when there are more than one request may carry', async () => {
        // A reader who loads a third page, or merges several sections into the flat list, tracks more
        // rows than the endpoint answers for in one request. Cutting the list short there would leave
        // those rows without a glyph for as long as they stayed on screen.
        const reportIds = Array.from({ length: PR_CI_STATUS_MAX_REPORTS + 5 }, (_, index) => `report-${index}`)
        answers = Object.fromEntries(reportIds.map((reportId) => [reportId, 'passing']))

        logic.actions.trackReports('needs-decision', reportIds)
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedIds).toHaveLength(2)
        expect(requestedIds.every((ids) => ids.length <= PR_CI_STATUS_MAX_REPORTS)).toBe(true)
        expect(requestedIds.flat().sort()).toEqual([...reportIds].sort())
        expect(Object.keys(logic.values.ciStatusByReportId)).toHaveLength(reportIds.length)
    })

    it('holds the last known state for a report the next answer leaves out', async () => {
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()

        // GitHub rate-limiting a poll drops the report from the answer. Clearing its glyph would
        // read as "this pull request has no checks", which is a different and wrong claim.
        answers = {}
        logic.actions.loadCiStatuses({ reportIds: ['report-1'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.ciStatusByReportId).toEqual({ 'report-1': 'failing' })
    })

    it('stops showing a state nothing has confirmed for two polls', async () => {
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()

        // A rate limit that lasts, or access GitHub has revoked, leaves the report out of every
        // answer. Holding the glyph indefinitely would let the pill claim a pull request is failing
        // or passing long after its CI moved on.
        const confirmedAt = Date.now()
        answers = {}
        const nowSpy = jest.spyOn(Date, 'now').mockReturnValue(confirmedAt + PR_CI_STATUS_MAX_AGE_MS + 1)
        try {
            logic.actions.loadCiStatuses({ reportIds: ['report-1'] })
            await expectLogic(logic).toFinishAllListeners()
        } finally {
            nowSpy.mockRestore()
        }

        expect(logic.values.ciStatusByReportId).toEqual({})
    })

    it('forgets a report that has left the tracked set', async () => {
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()

        // Otherwise the map grows for as long as the inbox stays open.
        logic.actions.loadCiStatuses({ reportIds: ['report-2'] })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.ciStatusByReportId).toEqual({ 'report-2': 'passing' })
    })

    it('does not re-ask for reports it has already requested', async () => {
        // Every list re-render announces the same rows; re-fetching each time would hammer GitHub.
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()

        expect(requestedIds).toHaveLength(1)
    })

    it('asks again for a row the section dropped and then showed again', async () => {
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()

        // Filtering the inbox to resolved reports leaves a section with nothing to announce, and the
        // poll pauses while nothing is tracked. Repainting the old glyph when the filter clears would
        // claim a CI state of unknown age.
        logic.actions.trackReports('needs-decision', [])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.ciStatusByReportId).toEqual({})

        answers = { 'report-1': 'passing' }
        logic.actions.trackReports('needs-decision', ['report-1'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.ciStatusByReportId).toEqual({ 'report-1': 'passing' })
        // An empty announcement is answered without a request, so only the two real loads count.
        expect(requestedIds).toHaveLength(2)
    })

    it('retires the rows a section stops showing', async () => {
        // A narrowed filter drops rows from a section. Keeping them would leave the poll asking
        // GitHub about pull requests nobody is looking at, for as long as the inbox stays open.
        logic.actions.trackReports('needs-decision', ['report-1', 'report-2'])
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.trackReports('needs-decision', ['report-2'])
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.trackedReportIds).toEqual(['report-2'])
    })
})
