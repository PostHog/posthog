import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'
import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { mockTask } from '../../__mocks__/inboxMocks'
import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic, REPORT_AI_PANEL_ID } from '../../inboxTaskKickoffLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { ImplementButton } from './ImplementButton'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

function makeReport(): SignalReport {
    return {
        id: 'report-1',
        title: 'Exceptions spiked',
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('ImplementButton', () => {
    let createPrFromReport: jest.Mock

    beforeEach(() => {
        initKeaTests()
        window.localStorage.removeItem('inbox-report-implementation-prompt:combo')
        inboxTaskKickoffLogic.mount()
        createPrFromReport = jest.fn()
        jest.spyOn(inboxTaskKickoffLogic.actions, 'createPrFromReport').mockImplementation(createPrFromReport)
        jest.mocked(captureInboxReportAction).mockClear()
        jest.mocked(copyToClipboard).mockClear()
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    async function openMenu(): Promise<ReturnType<typeof userEvent.setup>> {
        const user = userEvent.setup()
        render(<ImplementButton report={makeReport()} />)
        await user.click(screen.getByTestId('inbox-report-create-pr-steer'))
        await waitFor(() => expect(screen.getByText('Implement with PostHog')).toBeInTheDocument())
        return user
    }

    it('starts a PostHog agent from the main action', async () => {
        const user = userEvent.setup()
        render(<ImplementButton report={makeReport()} />)

        await user.click(screen.getByTestId('inbox-report-create-pr'))

        expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: false })
    })

    it.each([TaskRunStatus.QUEUED, TaskRunStatus.IN_PROGRESS])(
        'opens the existing %s task instead of starting another',
        async (status) => {
            const user = userEvent.setup()
            const report = makeReport()
            const detail = inboxReportDetailLogic({ reportId: report.id, report })
            detail.mount()
            await expectLogic(detail).toFinishAllListeners()
            const task = mockTask('implementation-task', status)
            detail.actions.loadReportTasksSuccess([
                { task, purpose: 'implementation', purposeLabel: 'Implementation', startedAt: task.created_at },
            ])
            render(<ImplementButton report={report} />)

            expect(screen.queryByTestId('inbox-report-create-pr')).not.toBeInTheDocument()
            await user.click(screen.getByTestId('inbox-report-open-task'))

            expect(createPrFromReport).not.toHaveBeenCalled()
            expect(runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation).toMatchObject({
                taskId: task.id,
                runId: task.latest_run.id,
            })
            detail.unmount()
        }
    )

    it('opens both implementation options without starting work', async () => {
        await openMenu()

        expect(screen.getByText('Implement with PostHog')).toBeInTheDocument()
        expect(screen.getByText('Copy prompt for your agent')).toBeInTheDocument()
        expect(createPrFromReport).not.toHaveBeenCalled()
        expect(copyToClipboard).not.toHaveBeenCalled()
    })

    it.each([
        [
            'the PostHog button',
            (user: ReturnType<typeof userEvent.setup>) =>
                user.click(screen.getByTestId('inbox-report-create-pr-submit')),
        ],
        ['Enter', (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Enter}')],
    ])('passes steering instructions with %s', async (_method, submit) => {
        const user = await openMenu()

        await user.type(
            screen.getByPlaceholderText('Add instructions for the PostHog agent (optional)'),
            '  Keep the existing API  '
        )
        await submit(user)

        expect(createPrFromReport).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'report-1' }),
            'Keep the existing API'
        )
        expect(jest.mocked(captureInboxReportAction).mock.calls[0][0].extra).toEqual({ has_feedback: true })
    })

    it('copies a prompt that claims the report and attaches the finished pull request', async () => {
        const user = await openMenu()

        await user.click(screen.getByTestId('inbox-report-copy-implementation-prompt'))

        const prompt = jest.mocked(copyToClipboard).mock.calls[0][0]
        expect(prompt).toContain('report ID: report-1')
        expect(prompt).toContain('inbox-report-artefacts-list')
        expect(prompt).toContain('claim the report with inbox-reports-claim')
        expect(prompt).toContain('pr_url to attach it')
        expect(prompt).toContain('release=true')
        expect(copyToClipboard).toHaveBeenCalledWith(prompt, 'prompt for your agent')
        expect(captureInboxReportAction).toHaveBeenCalledWith(
            expect.objectContaining({
                actionType: 'copy_implementation_prompt',
                extra: { agent: 'clipboard' },
            })
        )
    })

    it('opens the implementation prompt from the agent list without changing the copy action', async () => {
        const user = await openMenu()
        const open = jest.spyOn(window, 'open').mockImplementation()

        await user.click(screen.getByLabelText('Open prompt in an agent'))

        expect(screen.queryByText('PostHog AI')).not.toBeInTheDocument()
        await user.click(screen.getByText('Claude Code'))

        expect(open).toHaveBeenCalledWith(expect.stringMatching(/^claude-cli:\/\/open\?q=/), '_blank')
        expect(captureInboxReportAction).toHaveBeenCalledWith(
            expect.objectContaining({
                actionType: 'copy_implementation_prompt',
                extra: { agent: 'claude-code' },
            })
        )

        await user.click(screen.getByTestId('inbox-report-copy-implementation-prompt'))

        expect(copyToClipboard).toHaveBeenCalledWith(
            expect.stringContaining('report ID: report-1'),
            'prompt for your agent'
        )
    })

    describe('a start refused over a run the pane never saw', () => {
        let artefactRequests: number

        beforeEach(() => {
            artefactRequests = 0
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': () => {
                        artefactRequests += 1
                        return {
                            results:
                                artefactRequests > 1
                                    ? [
                                          {
                                              id: 'implementation-artefact',
                                              type: 'task_run',
                                              content: {
                                                  task_id: 'task-9',
                                                  run_id: 'task-9-run',
                                                  product: 'signals',
                                                  type: 'implementation',
                                              },
                                              created_at: '2026-01-01T00:00:00Z',
                                          },
                                      ]
                                    : [],
                        }
                    },
                    '/api/projects/:team_id/tasks/task-9/': mockTask('task-9', TaskRunStatus.IN_PROGRESS),
                    '/api/projects/:team_id/tasks/@me/config/': [
                        200,
                        { ai_run_preferences: {}, resolved_ai_run_defaults: null },
                    ],
                    '/api/projects/:team_id/signals/reports/:id/signals/': [],
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                },
                post: {
                    // The report cap refuses task creation and names the task holding the slot.
                    '/api/projects/:team_id/tasks/': () => [
                        429,
                        {
                            code: 'signal_report_task_cap',
                            error: 'A pull request run is already in progress for this report. Open the run to follow it.',
                            task_id: 'task-9',
                        },
                    ],
                },
            })
            initKeaTests()
            inboxTaskKickoffLogic.mount()
            inboxReportDetailLogic({ reportId: 'report-1', report: makeReport() }).mount()
        })

        afterEach(() => {
            cleanup()
            jest.restoreAllMocks()
        })

        it('offers the run and replaces Implement with View task', async () => {
            const toast = jest.spyOn(lemonToast, 'error')
            const user = userEvent.setup()
            render(<ImplementButton report={makeReport()} />)
            await waitFor(() => expect(artefactRequests).toBeGreaterThan(0))
            const beforeRefusal = artefactRequests

            await user.click(screen.getByTestId('inbox-report-create-pr'))

            // The refusal reaches the person as a toast that offers the run it names.
            const capToast = await waitFor(() => {
                const call = toast.mock.calls.find(([message]) =>
                    String(message).includes('already in progress for this report')
                )
                expect(call).not.toBeUndefined()
                return call!
            })
            expect(capToast[1]?.button?.label).toBe('Open run')

            // The pane re-reads the artefact log, so the run it never saw now lists and the button
            // becomes View task instead of a press the server keeps refusing.
            await waitFor(() => expect(artefactRequests).toBe(beforeRefusal + 1))
            expect(await screen.findByTestId('inbox-report-open-task')).toBeInTheDocument()
            expect(screen.queryByTestId('inbox-report-create-pr')).not.toBeInTheDocument()

            void capToast[1]?.button?.action()
            expect(router.values.location.pathname).toContain('/tasks/task-9')
        })
    })
})
