import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'

import { makeReport } from './__mocks__/inboxMocks'
import {
    FREE_TRIAL_PR_DISABLED_REASON,
    REPORT_AI_PANEL,
    REPORT_AI_PANEL_ID,
    buildCreatePrReportPrompt,
    buildDiscussReportPrompt,
    inboxTaskKickoffLogic,
} from './inboxTaskKickoffLogic'
import { SignalReportStatus } from './types'

describe('inboxTaskKickoffLogic', () => {
    describe('report sidebar', () => {
        let logic: ReturnType<typeof inboxTaskKickoffLogic.build>
        let createdTasks: Record<string, unknown>[]
        let startedRuns: Record<string, unknown>[]
        // Runs while the kickoff awaits its run response, so a test can act as the reader does mid-flight.
        let onRunRequest: (() => void) | null
        const report = makeReport({ id: 'report-sidebar', status: SignalReportStatus.READY })

        beforeEach(() => {
            localStorage.clear()
            createdTasks = []
            startedRuns = []
            onRunRequest = null
            useMocks({
                get: {
                    '/api/projects/:team/signals/reports/:id/': report,
                },
                post: {
                    '/api/projects/:team/tasks/': async ({ request }) => {
                        createdTasks.push((await request.json()) as Record<string, unknown>)
                        return [201, { id: 'report-task' }]
                    },
                    '/api/projects/:team/tasks/:id/run/': async ({ request }) => {
                        startedRuns.push((await request.json()) as Record<string, unknown>)
                        onRunRequest?.()
                        return [200, { id: 'report-task', latest_run: { id: 'report-run' } }]
                    },
                },
            })
            initKeaTests()
            logic = inboxTaskKickoffLogic()
            logic.mount()
        })

        afterEach(() => logic.unmount())

        it.each(['implementation', 'discussion'] as const)(
            'opens one %s run without leaving the report',
            async (relationship) => {
                const originalPath = router.values.location.pathname
                await expectLogic(logic, () => {
                    if (relationship === 'implementation') {
                        logic.actions.createPrFromReport(report)
                    } else {
                        logic.actions.discussReport(report, 'https://example.com/report', 'Explain the recommendation')
                    }
                }).toFinishAllListeners()

                expect(createdTasks).toHaveLength(1)
                expect(createdTasks[0]).toMatchObject({
                    signal_report: report.id,
                    signal_report_task_relationship: relationship,
                })
                expect(startedRuns).toHaveLength(1)
                expect(startedRuns[0]).toMatchObject({
                    signal_report_id: report.id,
                    mode: 'interactive',
                    pending_user_message: expect.any(String),
                })
                expect(router.values.location.pathname).toBe(originalPath)
                expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
                expect(sidePanelStateLogic.values.selectedTabOptions).toBe(REPORT_AI_PANEL)
                expect(runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation).toMatchObject({
                    taskId: 'report-task',
                    runId: 'report-run',
                })
                expect(logic.values.reportChatContext?.report.id).toBe(report.id)

                logic.actions.openReportTask(report, 'report-task', 'report-run')
                expect(createdTasks).toHaveLength(1)
                expect(startedRuns).toHaveLength(1)
            }
        )

        // A kickoff is two round trips, and a report's View task button stays live throughout, so the
        // reader can open another report's run before this one lands. The panel is shared, so opening
        // the finished task regardless would pull the sidebar off whatever they picked last.
        it.each(['implementation', 'discussion'] as const)(
            'leaves a newer pick in the sidebar when the %s kickoff lands after it',
            async (relationship) => {
                const otherReport = makeReport({ id: 'report-other', status: SignalReportStatus.READY })
                onRunRequest = () => logic.actions.openReportTask(otherReport, 'other-task', 'other-run')

                await expectLogic(logic, () => {
                    if (relationship === 'implementation') {
                        logic.actions.createPrFromReport(report)
                    } else {
                        logic.actions.discussReport(report, 'https://example.com/report', 'Explain the recommendation')
                    }
                }).toFinishAllListeners()

                expect(startedRuns).toHaveLength(1)
                expect(runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation).toMatchObject({
                    taskId: 'other-task',
                    runId: 'other-run',
                })
                expect(logic.values.reportChatContext?.report.id).toBe(otherReport.id)
            }
        )

        it('sends Back to the report composer even when the shared panel left history open', () => {
            const panel = runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID })
            // The PostHog AI side panel shares this panel state, so its history can already be open.
            panel.actions.setHistoryExpanded(true)

            logic.actions.openReportTask(report, 'report-task', 'report-run')
            panel.actions.goBack()

            expect(panel.values.historyExpanded).toBe(false)
            expect(panel.values.activeCreation).toBeNull()
        })
    })

    describe('freeTrialDisabledReason', () => {
        let logic: ReturnType<typeof inboxTaskKickoffLogic.build>

        beforeEach(() => {
            // featureFlagLogic persists to localStorage, which jsdom keeps across tests.
            localStorage.clear()
            initKeaTests()
            featureFlagLogic.mount()
            logic = inboxTaskKickoffLogic()
            logic.mount()
        })

        afterEach(() => {
            logic.unmount()
        })

        it.each([
            [true, FREE_TRIAL_PR_DISABLED_REASON],
            [false, null],
        ])('with the free trial flag %s, Create PR carries %s', (enabled, expected) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SELF_DRIVING_FREE_TRIAL], {
                [FEATURE_FLAGS.SELF_DRIVING_FREE_TRIAL]: enabled,
            })
            expect(logic.values.freeTrialDisabledReason).toBe(expected)
        })
    })

    describe('buildDiscussReportPrompt', () => {
        const url = 'https://app.posthog.com/project/1/inbox/report-1'

        it.each([SignalReportStatus.READY, SignalReportStatus.PENDING_INPUT])(
            'tells the agent to carry out actions for a %s report',
            (status) => {
                const prompt = buildDiscussReportPrompt(
                    makeReport({ status }),
                    url,
                    'Create the alert the report recommends'
                )
                expect(prompt).toContain('carry the action out')
                expect(prompt).toContain(url)
                expect(prompt).toContain('inbox-reports-set-state')
                // A discussion run can open a PR too, so it carries the Create PR prompt's guard: a
                // resolve through the state API closes the report's open PR.
                expect(prompt).toContain('would close the PR you just opened')
                // The state API has no ownership precondition, so the prompt is the only thing keeping
                // a discussion run from ending work another run holds.
                expect(prompt).toContain('leave its state alone when somebody else holds it')
            }
        )

        // Only judged, still-active reports may drive actions: pre-judgment statuses carry unjudged
        // pipeline content, suppressed/failed reports carry the content the judge rejected, and a
        // resolved report's persisted action suggestions would redo already-completed work.
        it.each([
            SignalReportStatus.POTENTIAL,
            SignalReportStatus.CANDIDATE,
            SignalReportStatus.IN_PROGRESS,
            SignalReportStatus.RESOLVED,
            SignalReportStatus.SUPPRESSED,
            SignalReportStatus.FAILED,
            SignalReportStatus.DELETED,
        ])('pins the agent to answering for a %s report', (status) => {
            const prompt = buildDiscussReportPrompt(makeReport({ status }), url, 'Carry out the recommendation')
            expect(prompt).toContain('Answer this question')
            expect(prompt).not.toContain('carry the action out')
            // An answer-only run changes nothing about the report, so it is never told to touch the state.
            expect(prompt).not.toContain('inbox-reports-set-state')
        })

        it.each([
            // A fix is already in flight, so acting on the recommendations would duplicate it — the same
            // reason autostart and Create PR eligibility exclude already-addressed reports.
            ['an already-addressed report', makeReport({ status: SignalReportStatus.READY, already_addressed: true })],
            // The actionability judge said there is no work to act on, so an action framing would invite
            // acting anyway — the same judgment that hides Create PR.
            [
                'a report judged not actionable',
                makeReport({ status: SignalReportStatus.READY, actionability: 'not_actionable' }),
            ],
            // An implementation PR already exists for this report, so carrying a stored "implement the
            // fix" suggestion out would open a second PR for the same work — the same field that hides
            // Create PR.
            [
                'a report with an implementation PR',
                makeReport({
                    status: SignalReportStatus.READY,
                    implementation_pr_url: 'https://github.com/x/y/pull/1',
                }),
            ],
            // null = the kickoff refetch could not confirm the report's current state; fail closed.
            ['an unconfirmed report state', null],
        ])('pins the agent to answering for %s', (_name, report) => {
            const prompt = buildDiscussReportPrompt(report, url, 'Carry out the recommendation')
            expect(prompt).toContain('Answer this question')
            expect(prompt).not.toContain('carry the action out')
        })
    })

    describe('buildCreatePrReportPrompt', () => {
        it('tells the agent how to leave the report state', () => {
            const prompt = buildCreatePrReportPrompt(makeReport({ status: SignalReportStatus.READY }))
            expect(prompt).toContain('open a PR')
            expect(prompt).toContain('inbox-reports-set-state')
            expect(prompt).toContain('fixed_outside_posthog')
            expect(prompt).toContain('suppressed')
            // Suppressing leaves the claim standing, so the run has to drop it itself.
            expect(prompt).toContain('then release your claim')
            // The claim is taken once, at task creation, so a rerun starts unclaimed.
            expect(prompt).toContain('claim it again first')
            // Resolving through the state API closes the report's open PR, so the run must not report
            // the PR it just opened as a resolution.
            expect(prompt).toContain('Do NOT set the state to resolved because you opened a PR')
        })

        it('keeps the user feedback after the state instructions', () => {
            const prompt = buildCreatePrReportPrompt(
                makeReport({ status: SignalReportStatus.READY }),
                'check the retries'
            )
            expect(prompt.indexOf('inbox-reports-set-state')).toBeLessThan(prompt.indexOf('check the retries'))
        })
    })
})
