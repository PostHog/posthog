import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport } from '../types'
import { inboxReportDetailLogic } from './inboxReportDetailLogic'

const REPORT = { id: 'report-1', status: 'ready', title: 'Checkout errors spiked' } as unknown as SignalReport

describe('inboxReportDetailLogic', () => {
    describe('feedback note submission', () => {
        let logic: ReturnType<typeof inboxReportDetailLogic.build>
        let notePosts: number
        let bareRatingPosts: number

        beforeEach(() => {
            notePosts = 0
            bareRatingPosts = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                    '/api/projects/:team_id/signals/reports/:id/signals/': [],
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                },
                post: {
                    '/api/projects/:team_id/signals/reports/:id/feedback/': async ({ request }) => {
                        const body = (await request.json()) as { note?: string }
                        if (body.note) {
                            notePosts += 1
                        } else {
                            bareRatingPosts += 1
                        }
                        return [200, { forwarded: Boolean(body.note) }]
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

            // The rating itself posts once (consumption evidence), the note once despite the double-click.
            expect(bareRatingPosts).toBe(1)
            expect(notePosts).toBe(1)
            expect(logic.values.feedbackNoteSubmitting).toBe(false)

            // Re-rating reopens the note flow; the guard must have reset or this submit is silently dropped.
            logic.actions.rateReport('negative')
            logic.actions.submitFeedbackNote('actually this was stale')
            await expectLogic(logic).toFinishAllListeners()

            expect(bareRatingPosts).toBe(2)
            expect(notePosts).toBe(2)
        })
    })

    describe('PR checks fetching', () => {
        const PR_REPORT = {
            id: 'report-2',
            status: 'ready',
            title: 'Checkout errors spiked',
            implementation_pr_url: 'https://github.com/example/repo/pull/1',
        } as unknown as SignalReport

        let logic: ReturnType<typeof inboxReportDetailLogic.build>
        let prChecksRequests: number

        beforeEach(() => {
            prChecksRequests = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                    '/api/projects/:team_id/signals/reports/:id/signals/': [],
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                    '/api/projects/:team_id/signals/reports/:id/pr_checks/': () => {
                        prChecksRequests += 1
                        return [502, { error: 'GitHub could not return the checks for this pull request.' }]
                    },
                    '/api/projects/:team_id/signals/reports/:id/pr_comments/': { comments: [] },
                },
            })
            initKeaTests()
            silenceKeaLoadersErrors()
            logic = inboxReportDetailLogic({ reportId: PR_REPORT.id, report: PR_REPORT })
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
            resumeKeaLoadersErrors()
        })

        it('does not endlessly retry a failing checks fetch', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(prChecksRequests).toBe(1)
            expect(logic.values.prChecksError).toBeTruthy()

            // The shell refreshes the report prop on its list poll; a failed load must not re-fire then.
            logic.actions.setReport(PR_REPORT)
            await expectLogic(logic).toFinishAllListeners()
            expect(prChecksRequests).toBe(1)

            // Two more failures (as the 15s poll would produce) reach the cap and back the poll off.
            logic.actions.loadPrChecks()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.prChecksBackedOff).toBe(false)
            logic.actions.loadPrChecks()
            await expectLogic(logic).toFinishAllListeners()

            expect(prChecksRequests).toBe(3)
            expect(logic.values.prChecksBackedOff).toBe(true)
            expect(logic.values.prChecksError).toBeTruthy()
        })
    })
})
