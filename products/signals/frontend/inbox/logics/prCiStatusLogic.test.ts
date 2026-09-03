/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { prCiStatusLogic } from './prCiStatusLogic'

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
