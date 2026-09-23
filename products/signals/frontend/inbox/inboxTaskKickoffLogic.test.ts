import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { attachedContextLogic, runnerPanelLogic, runStreamLogic } from 'products/posthog_ai/frontend/api/logics'

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
        let warmRequests: Record<string, unknown>[]
        let cancelledRuns: { taskId: string; runId: string; body: Record<string, unknown> }[]
        let warmResponse: Record<string, unknown>
        let warmResponses: Record<string, unknown>[]
        // Holds every warm response until the test resolves it, so a test can act mid-flight.
        let warmGate: Promise<void> | null
        let createResponse: Record<string, unknown>
        let createStatus: number
        // Runs while the kickoff awaits its run response, so a test can act as the reader does mid-flight.
        let onRunRequest: (() => void) | null
        const report = makeReport({ id: 'report-sidebar', status: SignalReportStatus.READY })

        beforeEach(() => {
            localStorage.clear()
            createdTasks = []
            startedRuns = []
            warmRequests = []
            cancelledRuns = []
            warmResponse = {}
            warmResponses = []
            warmGate = null
            createResponse = { id: 'report-task' }
            createStatus = 201
            onRunRequest = null
            useMocks({
                get: {
                    '/api/projects/:team/signals/reports/:id/': report,
                },
                post: {
                    '/api/projects/:team/tasks/': async ({ request }) => {
                        createdTasks.push((await request.json()) as Record<string, unknown>)
                        if (createStatus !== 201) {
                            return [
                                createStatus,
                                { code: 'signal_report_task_cap', error: 'Report task limit reached' },
                            ]
                        }
                        return [201, createResponse]
                    },
                    '/api/projects/:team/tasks/warm/': async ({ request }) => {
                        warmRequests.push((await request.json()) as Record<string, unknown>)
                        if (warmGate) {
                            await warmGate
                        }
                        return [200, warmResponses.shift() ?? warmResponse]
                    },
                    '/api/projects/:team/tasks/:taskId/runs/:runId/cancel/': async ({ request, params }) => {
                        cancelledRuns.push({
                            taskId: String(params.taskId),
                            runId: String(params.runId),
                            body: (await request.json()) as Record<string, unknown>,
                        })
                        return [200, { id: params.runId }]
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
                if (relationship === 'discussion') {
                    attachedContextLogic.actions.registerContext('test-picker', [
                        { type: 'insight', key: 'insight-one', label: 'Conversion rate' },
                    ])
                }
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
                if (relationship === 'discussion') {
                    expect(createdTasks[0]).toMatchObject({
                        description: expect.stringContaining('- insight insight-one ("Conversion rate")'),
                        signal_report_discussion_question: 'Explain the recommendation',
                        branch: null,
                        model: 'claude-opus-5',
                    })
                    expect(createdTasks[0].pending_user_message).toBe(createdTasks[0].description)
                    expect(startedRuns[0].pending_user_message).toBe(createdTasks[0].description)
                    expect(attachedContextLogic.values.sentContextKeysByTask['report-task']).toContain(
                        'insight:insight-one'
                    )
                }
                expect(router.values.location.pathname).toBe(originalPath)
                expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
                expect(sidePanelStateLogic.values.selectedTabOptions).toBe(REPORT_AI_PANEL)
                const activeCreation = runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation
                expect(activeCreation).toMatchObject({
                    taskId: 'report-task',
                    runId: 'report-run',
                })
                expect(activeCreation?.streamKey).not.toBe('report-run')
                const stream = runStreamLogic({ streamKey: activeCreation!.streamKey })
                const unmountStream = stream.mount()
                expect(stream.values.awaitingOptimisticAttach).toBe(true)
                expect(stream.values.hasThreadItems).toBe(relationship === 'discussion')
                unmountStream()
                expect(logic.values.reportChatContext?.report.id).toBe(report.id)

                logic.actions.openReportTask(report, 'report-task', 'report-run')
                expect(createdTasks).toHaveLength(1)
                expect(startedRuns).toHaveLength(1)
            }
        )

        it('warms a repo-less sandbox for the report when Ask AI opens, and only once per report', async () => {
            warmResponse = { task_id: 'warm-task', run_id: 'warm-run' }

            await expectLogic(logic, () => {
                logic.actions.openReportDiscussion(report, 'https://example.com/report')
                logic.actions.openReportDiscussion(report, 'https://example.com/report')
            }).toFinishAllListeners()

            expect(warmRequests).toHaveLength(1)
            expect(warmRequests[0]).toMatchObject({
                origin_product: 'signal_report',
                signal_report: report.id,
                branch: null,
                runtime_adapter: 'claude',
                model: 'claude-opus-5',
            })
            expect(warmRequests[0]).not.toHaveProperty('repository')
            expect(logic.values.reportWarmLease).toEqual({
                reportId: report.id,
                taskId: 'warm-task',
                runId: 'warm-run',
            })
            expect(cancelledRuns).toHaveLength(0)
        })

        it('does not warm when Create PR opens the panel', async () => {
            await expectLogic(logic, () => logic.actions.createPrFromReport(report)).toFinishAllListeners()

            expect(warmRequests).toHaveLength(0)
            expect(createdTasks[0]).not.toHaveProperty('branch')
        })

        it('reuses the warm run on submit instead of starting a second run', async () => {
            warmResponse = { task_id: 'warm-task', run_id: 'warm-run' }
            createResponse = { id: 'warm-task', latest_run: { id: 'warm-run' } }
            await expectLogic(logic, () =>
                logic.actions.openReportDiscussion(report, 'https://example.com/report')
            ).toFinishAllListeners()

            await expectLogic(logic, () =>
                logic.actions.discussReport(report, 'https://example.com/report', 'Explain the recommendation')
            ).toFinishAllListeners()

            expect(createdTasks).toHaveLength(1)
            expect(startedRuns).toHaveLength(0)
            expect(cancelledRuns).toHaveLength(0)
            expect(logic.values.reportWarmLease).toBeNull()
            expect(runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation).toMatchObject({
                taskId: 'warm-task',
                runId: 'warm-run',
            })
        })

        it.each([
            ['the side panel closes', (): void => sidePanelStateLogic.actions.closeSidePanel()],
            [
                'another side panel tab opens',
                (): void => sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Notebooks),
            ],
            [
                'the Max tab reopens without the report',
                (): void => sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max),
            ],
            ['the panel options leave the report', (): void => sidePanelStateLogic.actions.setSidePanelOptions(null)],
            [
                'another report opens',
                (): void =>
                    logic.actions.openReportDiscussion(
                        makeReport({ id: 'report-other', status: SignalReportStatus.READY }),
                        'https://example.com/other'
                    ),
            ],
        ])('releases the warm run when %s', async (_name, act) => {
            warmResponse = { task_id: 'warm-task', run_id: 'warm-run' }
            await expectLogic(logic, () =>
                logic.actions.openReportDiscussion(report, 'https://example.com/report')
            ).toFinishAllListeners()

            await expectLogic(logic, act).toFinishAllListeners()

            expect(cancelledRuns).toEqual([
                { taskId: 'warm-task', runId: 'warm-run', body: { only_if_awaiting_first_message: true } },
            ])
            expect(logic.values.reportWarmLease?.reportId ?? null).not.toBe(report.id)
        })

        it('warms one report at a time and hands the slot to the newest report', async () => {
            const otherReport = makeReport({ id: 'report-other', status: SignalReportStatus.READY })
            let settleWarm!: () => void
            warmGate = new Promise<void>((resolve) => {
                settleWarm = resolve
            })
            warmResponses = [
                { task_id: 'warm-task', run_id: 'warm-run' },
                { task_id: 'other-task', run_id: 'other-run' },
            ]

            logic.actions.openReportDiscussion(report, 'https://example.com/report')
            logic.actions.openReportDiscussion(otherReport, 'https://example.com/other')
            warmGate = null
            settleWarm()
            await expectLogic(logic).toFinishAllListeners()

            expect(warmRequests.map((request) => request.signal_report)).toEqual([report.id, otherReport.id])
            expect(cancelledRuns).toEqual([
                { taskId: 'warm-task', runId: 'warm-run', body: { only_if_awaiting_first_message: true } },
            ])
            expect(logic.values.reportWarmLease).toEqual({
                reportId: otherReport.id,
                taskId: 'other-task',
                runId: 'other-run',
            })
        })

        it('keeps the warm when the same report reopens before its warm settles', async () => {
            let settleWarm!: () => void
            warmGate = new Promise<void>((resolve) => {
                settleWarm = resolve
            })
            warmResponse = { task_id: 'warm-task', run_id: 'warm-run' }

            logic.actions.openReportDiscussion(report, 'https://example.com/report')
            sidePanelStateLogic.actions.closeSidePanel()
            logic.actions.openReportDiscussion(report, 'https://example.com/report')
            warmGate = null
            settleWarm()
            await expectLogic(logic).toFinishAllListeners()

            expect(warmRequests).toHaveLength(1)
            expect(cancelledRuns).toHaveLength(0)
            expect(logic.values.reportWarmLease).toEqual({
                reportId: report.id,
                taskId: 'warm-task',
                runId: 'warm-run',
            })
        })

        it('cancels the warm run when task creation fails', async () => {
            warmResponse = { task_id: 'warm-task', run_id: 'warm-run' }
            createStatus = 429
            await expectLogic(logic, () =>
                logic.actions.openReportDiscussion(report, 'https://example.com/report')
            ).toFinishAllListeners()

            await expectLogic(logic, () =>
                logic.actions.discussReport(report, 'https://example.com/report', 'Explain the recommendation')
            ).toFinishAllListeners()

            expect(createdTasks).toHaveLength(1)
            expect(startedRuns).toHaveLength(0)
            expect(logic.values.reportWarmLease).toBeNull()
            expect(logic.values.isDiscussing).toBe(false)
            await waitFor(() =>
                expect(cancelledRuns).toEqual([
                    { taskId: 'warm-task', runId: 'warm-run', body: { only_if_awaiting_first_message: true } },
                ])
            )
        })

        it('shows implementation provisioning before the run request finishes and attaches the result in place', async () => {
            let optimisticStreamKey: string | undefined
            onRunRequest = () => {
                const activeCreation = runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation
                expect(activeCreation?.taskId).toBeUndefined()
                expect(activeCreation?.runId).toBeUndefined()
                optimisticStreamKey = activeCreation?.streamKey
                expect(optimisticStreamKey).toMatch(/^report-implementation-/)

                const stream = runStreamLogic({ streamKey: optimisticStreamKey! })
                expect(stream.values.awaitingOptimisticAttach).toBe(true)
                expect(stream.values.streamPhase).toBe('provisioning')
                expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
                expect(sidePanelStateLogic.values.selectedTabOptions).toBe(REPORT_AI_PANEL)
            }

            await expectLogic(logic, () => logic.actions.createPrFromReport(report)).toFinishAllListeners()

            expect(optimisticStreamKey).not.toBeUndefined()
            expect(runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation).toEqual({
                streamKey: optimisticStreamKey,
                taskId: 'report-task',
                runId: 'report-run',
            })
        })

        it('keeps the optimistic stream when View task opens the run already shown in the panel', () => {
            const panel = runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID })
            panel.actions.setActiveCreation({
                streamKey: 'report-implementation-stream',
                taskId: 'report-task',
                runId: 'report-run',
            })

            logic.actions.openReportTask(report, 'report-task', 'report-run')

            expect(panel.values.activeCreation).toEqual({
                streamKey: 'report-implementation-stream',
                taskId: 'report-task',
                runId: 'report-run',
            })
        })

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
