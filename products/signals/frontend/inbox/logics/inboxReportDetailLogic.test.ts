import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport } from '../types'
import { inboxReportDetailLogic } from './inboxReportDetailLogic'

const REPORT = { id: 'report-1', status: 'ready', title: 'Checkout errors spiked' } as unknown as SignalReport

describe('inboxReportDetailLogic feedback note submission', () => {
    let logic: ReturnType<typeof inboxReportDetailLogic.build>
    let feedbackPosts: number

    beforeEach(() => {
        feedbackPosts = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                '/api/projects/:team_id/signals/reports/:id/signals/': [],
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:id/feedback/': () => {
                    feedbackPosts += 1
                    return [200, { forwarded: true }]
                },
            },
        })
        initKeaTests()
        logic = inboxReportDetailLogic({ reportId: REPORT.id, report: REPORT })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('posts once on a double-click and lets a revised note through after re-rating', async () => {
        logic.actions.rateReport('positive')
        // A double-click dispatches submit twice before the first request settles.
        logic.actions.submitFeedbackNote('the repro steps were right')
        logic.actions.submitFeedbackNote('the repro steps were right')
        await expectLogic(logic).toFinishAllListeners()

        expect(feedbackPosts).toBe(1)
        expect(logic.values.feedbackNoteSubmitting).toBe(false)

        // Re-rating reopens the note flow; the guard must have reset or this submit is silently dropped.
        logic.actions.rateReport('negative')
        logic.actions.submitFeedbackNote('actually this was stale')
        await expectLogic(logic).toFinishAllListeners()

        expect(feedbackPosts).toBe(2)
    })
})
