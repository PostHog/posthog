import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { ReportTaskPurpose } from '../components/detail/artefactTypes'
import { SignalReport } from '../types'
import { ReportTaskEntry, hasLiveImplementationTask, inboxReportDetailLogic } from './inboxReportDetailLogic'

const REPORT = { id: 'report-1', status: 'ready', title: 'Checkout errors spiked' } as unknown as SignalReport

const linkedTask = (purpose: ReportTaskPurpose, status: TaskRunStatus | null): ReportTaskEntry =>
    ({
        task: { latest_run: status ? { status } : null },
        purpose,
        purposeLabel: purpose,
        startedAt: '2026-01-01T00:00:00Z',
    }) as unknown as ReportTaskEntry

describe('inboxReportDetailLogic', () => {
    describe('hasLiveImplementationTask', () => {
        // Only `failed` and `cancelled` hand the report's implementation slot back server-side, so a
        // completed or still-running task has to keep the action disabled. Reusing the logic's
        // TERMINAL_RUN_STATUSES (which includes `completed`) is the tempting mistake these rows catch:
        // it would offer a second PR the server answers with a 429.
        it.each([
            { label: 'a task with no run yet', status: null, holdsSlot: true },
            { label: 'a not-started run', status: TaskRunStatus.NOT_STARTED, holdsSlot: true },
            { label: 'a queued run', status: TaskRunStatus.QUEUED, holdsSlot: true },
            { label: 'a run in progress', status: TaskRunStatus.IN_PROGRESS, holdsSlot: true },
            { label: 'a completed run', status: TaskRunStatus.COMPLETED, holdsSlot: true },
            { label: 'a failed run', status: TaskRunStatus.FAILED, holdsSlot: false },
            { label: 'a cancelled run', status: TaskRunStatus.CANCELLED, holdsSlot: false },
        ])('$label holds the report implementation slot: $holdsSlot', ({ status, holdsSlot }) => {
            expect(hasLiveImplementationTask([linkedTask('implementation', status)])).toBe(holdsSlot)
        })

        it('ignores tasks that are not implementations, and an unloaded list', () => {
            expect(hasLiveImplementationTask([linkedTask('research', TaskRunStatus.IN_PROGRESS)])).toBe(false)
            expect(hasLiveImplementationTask([linkedTask('other', TaskRunStatus.IN_PROGRESS)])).toBe(false)
            expect(hasLiveImplementationTask(null)).toBe(false)
        })
    })

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

    describe('report task polling', () => {
        let logic: ReturnType<typeof inboxReportDetailLogic.build>
        let artefactRequests: number

        beforeEach(() => {
            artefactRequests = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': () => {
                        artefactRequests += 1
                        return { results: [] }
                    },
                    '/api/projects/:team_id/signals/reports/:id/signals/': [],
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                },
            })
            initKeaTests()
            logic = inboxReportDetailLogic({ reportId: REPORT.id, report: REPORT })
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        // `ready` is not one of the active statuses, so the report's own status never starts the poll.
        // An implementation run under it still settles, and a failed or cancelled one hands the Create PR
        // slot back, so the run has to hold the poll open by itself or the action stays disabled until the
        // pane is reopened. A completed run must not hold it open: it keeps the slot for good, and polling
        // past it would never observe a change.
        it.each([
            { label: 'no linked tasks', tasks: [], polls: false },
            { label: 'an implementation with no run yet', tasks: [linkedTask('implementation', null)], polls: true },
            {
                label: 'an implementation in progress',
                tasks: [linkedTask('implementation', TaskRunStatus.IN_PROGRESS)],
                polls: true,
            },
            {
                label: 'a completed implementation',
                tasks: [linkedTask('implementation', TaskRunStatus.COMPLETED)],
                polls: false,
            },
            {
                label: 'a failed implementation',
                tasks: [linkedTask('implementation', TaskRunStatus.FAILED)],
                polls: false,
            },
            {
                label: 'a research task in progress',
                tasks: [linkedTask('research', TaskRunStatus.IN_PROGRESS)],
                polls: false,
            },
        ])('a ready report with $label polls: $polls', ({ tasks, polls }) => {
            logic.actions.loadReportTasksSuccess(tasks)

            expect(logic.values.shouldPollReportTasks).toBe(polls)
        })

        it('refreshes the artefact log once a PR task starts', async () => {
            await expectLogic(logic).toFinishAllListeners()
            const beforeKickoff = artefactRequests

            // Without this the gate keeps reading the pre-kickoff task list, so a ready report offers
            // Create PR a second time and the server answers the press with a 429.
            logic.actions.createPrSuccess()
            await expectLogic(logic).toFinishAllListeners()

            expect(artefactRequests).toBe(beforeKickoff + 1)
        })
    })
})
