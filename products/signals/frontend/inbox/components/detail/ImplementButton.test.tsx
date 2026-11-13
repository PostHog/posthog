/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'

import { mockTask, myAgentClaim, myClaim, teammateClaim } from '../../__mocks__/inboxMocks'
import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxTaskKickoffLogic, REPORT_AI_PANEL_ID } from '../../inboxTaskKickoffLogic'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { SignalReport, SignalReportStatus } from '../../types'
import { ImplementButton } from './ImplementButton'

jest.mock('../../inboxAnalytics', () => ({
    ...jest.requireActual('../../inboxAnalytics'),
    captureInboxReportAction: jest.fn(),
}))

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn().mockResolvedValue(true),
}))

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
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
        ...overrides,
    } satisfies SignalReport
}

describe('ImplementButton', () => {
    let createPrFromReport: jest.Mock

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': {
                    results: [{ id: 1, kind: 'github', installation_status: 'connected' }],
                    next: null,
                },
            },
        })
        initKeaTests()
        window.localStorage.removeItem('inbox-report-implementation-prompt:combo')
        inboxTaskKickoffLogic.mount()
        createPrFromReport = jest.fn()
        jest.spyOn(inboxTaskKickoffLogic.actions, 'createPrFromReport').mockImplementation(createPrFromReport)
        jest.mocked(captureInboxReportAction).mockReset()
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

    it('starts a PostHog agent from the main button without opening the options', async () => {
        const user = userEvent.setup()
        const capture = jest.spyOn(posthog, 'capture')
        jest.mocked(captureInboxReportAction).mockImplementation(
            jest.requireActual('../../inboxAnalytics').captureInboxReportAction
        )
        render(<ImplementButton report={makeReport()} />)

        await user.click(screen.getByTestId('inbox-report-create-pr'))

        expect(screen.queryByTestId('inbox-report-create-pr-submit')).not.toBeInTheDocument()
        await waitFor(() =>
            expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        )
        expect(
            capture.mock.calls.filter(([, properties]) => properties?.action_type === 'implementation_button_clicked')
        ).toEqual([
            [
                'Inbox report action',
                expect.objectContaining({
                    action_type: 'implementation_button_clicked',
                    surface: 'detail_pane',
                    button_action: 'implement',
                    button_position: 'body',
                }),
                undefined,
            ],
        ])
        expect(
            jest.mocked(captureInboxReportAction).mock.calls.find(([event]) => event.actionType === 'create_pr')?.[0]
                .extra
        ).toEqual({
            has_feedback: false,
            claim_step: 'start',
            opened_from_link: false,
        })
    })

    it.each([
        ['detail_pane', false],
        ['triage_mode', false],
        ['detail_pane', true],
    ] as const)(
        'offers a repository after automatic resolution fails from %s (retry loading: %s)',
        async (surface, retryLoading) => {
            let repositoriesFailed = retryLoading
            useMocks({
                get: {
                    '/api/projects/:team_id/integrations/': {
                        results: [{ id: 1, kind: 'github', display_name: 'Example' }],
                        next: null,
                    },
                    '/api/projects/:team_id/integrations/1/github_repos/': () =>
                        repositoriesFailed
                            ? [503, { detail: 'Try again.' }]
                            : {
                                  repositories: [{ id: 1, name: 'app', full_name: 'example/app' }],
                                  has_more: false,
                              },
                },
            })
            const user = userEvent.setup()
            const report = { ...makeReport(), repo_slug: null }
            render(<ImplementButton report={report} surface={surface} />)

            await user.click(
                screen.getByTestId(surface === 'triage_mode' ? 'inbox-triage-create-pr' : 'inbox-report-create-pr')
            )
            expect(createPrFromReport).toHaveBeenCalledWith(report, undefined)
            expect(screen.queryByTestId('select-github-repository')).not.toBeInTheDocument()
            createPrFromReport.mockClear()

            const access = reportGithubAccessLogic({ report, surface })
            await expectLogic(access, () => access.actions.requireRepositorySelection()).toFinishAllListeners()
            await screen.findByText('Select a repository to implement this report')
            expect(createPrFromReport).not.toHaveBeenCalled()
            expect(screen.getByTestId('inbox-report-create-pr-submit')).toHaveAttribute('aria-disabled', 'true')
            await user.type(
                screen.getByPlaceholderText('Add instructions for the PostHog agent (optional)'),
                'Keep the API{Enter}'
            )
            expect(createPrFromReport).not.toHaveBeenCalled()

            if (retryLoading) {
                await screen.findByText('Could not load repositories. Try again.')
                repositoriesFailed = false
                await user.click(screen.getAllByText('Retry')[0])
                await waitFor(() =>
                    expect(screen.queryByText('Could not load repositories. Try again.')).not.toBeInTheDocument()
                )
            }
            await user.click(screen.getByTestId('select-github-repository'))
            await user.click(await screen.findByText('example/app'))
            await user.click(screen.getByTestId('inbox-report-create-pr-submit'))

            expect(createPrFromReport).toHaveBeenCalledWith(report, 'Keep the API', 'example/app')
            expect(captureInboxReportAction).toHaveBeenCalledWith(
                expect.objectContaining({
                    actionType: 'github_access_recovery',
                    extra: { stage: 'repository_selected', outcome: undefined },
                })
            )
        }
    )

    it('opens the implementation choices when a link asks for them', async () => {
        const user = userEvent.setup()
        const onChoicesOpenedFromLink = jest.fn()
        render(
            <ImplementButton
                report={makeReport()}
                openChoicesFromLink
                onChoicesOpenedFromLink={onChoicesOpenedFromLink}
            />
        )

        await waitFor(() => expect(screen.getByText('Implement with PostHog')).toBeInTheDocument())
        expect(onChoicesOpenedFromLink).toHaveBeenCalled()
        expect(createPrFromReport).not.toHaveBeenCalled()

        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))

        await waitFor(() =>
            expect(createPrFromReport).toHaveBeenCalledWith(expect.objectContaining({ id: 'report-1' }), undefined)
        )
        expect(
            jest.mocked(captureInboxReportAction).mock.calls.find(([event]) => event.actionType === 'create_pr')?.[0]
                .extra
        ).toEqual({
            has_feedback: false,
            claim_step: 'start',
            opened_from_link: true,
        })
    })

    // Starting on a teammate's claim without the takeover would fail the run, or move their work without telling
    // them. A takeover the server refuses must reload the claim, or a retry submits the same stale takeover.
    it.each([
        { name: 'starts the run after the takeover', claimStatus: 200, starts: true, openedFromLink: false },
        { name: 'keeps link attribution after the takeover', claimStatus: 200, starts: true, openedFromLink: true },
        { name: 'reloads the claim after a refused takeover', claimStatus: 409, starts: false, openedFromLink: false },
    ])("teammate's claim: $name", async ({ claimStatus, starts, openedFromLink }) => {
        const claimBodies: unknown[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/:id/claim/': async ({ request }) => {
                    claimBodies.push(await request.json())
                    return claimStatus === 200
                        ? [200, { ...makeReport(), assignee: myClaim }]
                        : [409, { detail: "The report's claim changed. Reload the report and try again." }]
                },
            },
        })
        const bulkActions = inboxBulkActionsLogic()
        bulkActions.mount()
        const user = userEvent.setup()
        render(
            <ImplementButton
                report={makeReport({ assignee: { ...teammateClaim, claim_id: 'claim-robin' } })}
                openChoicesFromLink={openedFromLink}
            />
        )

        await expectLogic(bulkActions, async () => {
            await user.click(
                screen.getByTestId(openedFromLink ? 'inbox-report-create-pr-submit' : 'inbox-report-create-pr')
            )
            expect(createPrFromReport).not.toHaveBeenCalled()
            await user.click(await screen.findByText('Take over and implement'))
        }).toDispatchActions([starts ? 'reportClaimChanged' : 'reportWriteFailed'])

        expect(claimBodies).toEqual([{ takeover: true, takeover_claim_id: 'claim-robin' }])
        if (starts) {
            await waitFor(() =>
                expect(createPrFromReport).toHaveBeenCalledWith(
                    expect.objectContaining({ assignee: myClaim }),
                    undefined
                )
            )
        } else {
            expect(createPrFromReport).not.toHaveBeenCalled()
        }
        expect(
            jest
                .mocked(captureInboxReportAction)
                .mock.calls.filter(([event]) => event.actionType === 'create_pr')
                .map(([event]) => event.extra)
        ).toEqual(
            starts
                ? [
                      {
                          has_feedback: false,
                          claim_step: 'take_over',
                          opened_from_link: openedFromLink,
                      },
                  ]
                : []
        )
    })

    // Without the dialog outcome, a run someone thought about and cancelled cannot be told apart from one never offered.
    it.each([
        { button: 'Start run', confirmed: true },
        { button: 'Cancel', confirmed: false },
    ])('records whether the own-agent dialog was confirmed ($button)', async ({ button, confirmed }) => {
        const user = userEvent.setup()
        render(<ImplementButton report={makeReport({ assignee: myAgentClaim })} openChoicesFromLink />)

        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))
        expect(createPrFromReport).not.toHaveBeenCalled()
        await user.click(await screen.findByText(button))

        await waitFor(() =>
            expect(captureInboxReportAction).toHaveBeenCalledWith(
                expect.objectContaining({
                    actionType: 'claim_dialog',
                    extra: { claim_step: 'confirm_own_agent', starts_run: true, confirmed },
                })
            )
        )
        expect(createPrFromReport).toHaveBeenCalledTimes(confirmed ? 1 : 0)
        expect(
            jest
                .mocked(captureInboxReportAction)
                .mock.calls.filter(([event]) => event.actionType === 'create_pr')
                .map(([event]) => event.extra)
        ).toEqual(
            confirmed
                ? [
                      {
                          has_feedback: false,
                          claim_step: 'confirm_own_agent',
                          opened_from_link: true,
                      },
                  ]
                : []
        )
    })

    // A second press while the first one still loads would start two runs.
    it('starts one run when Implement is pressed twice quickly', async () => {
        const report = makeReport()

        inboxTaskKickoffLogic.actions.implementReport(report, undefined, 'triage_mode')
        inboxTaskKickoffLogic.actions.implementReport(report, undefined, 'triage_mode')

        await waitFor(() => expect(createPrFromReport).toHaveBeenCalledTimes(1))
        await expectLogic(inboxTaskKickoffLogic).toFinishAllListeners()
        expect(createPrFromReport).toHaveBeenCalledTimes(1)
    })

    it.each([TaskRunStatus.QUEUED, TaskRunStatus.IN_PROGRESS])(
        'opens the existing %s task instead of starting another',
        async (status) => {
            const user = userEvent.setup()
            const capture = jest.spyOn(posthog, 'capture')
            jest.mocked(captureInboxReportAction).mockImplementationOnce(
                jest.requireActual('../../inboxAnalytics').captureInboxReportAction
            )
            const report = makeReport()
            const detail = inboxReportDetailLogic({ reportId: report.id, report })
            detail.mount()
            await expectLogic(detail).toFinishAllListeners()
            const task = mockTask('implementation-task', status)
            detail.actions.loadReportTasksSuccess([
                { task, purpose: 'implementation', purposeLabel: 'Implementation', startedAt: task.created_at },
            ])
            render(
                <ImplementButton
                    report={report}
                    position="header"
                    reportTaskToOpen={detail.values.reportTaskToOpen}
                    implementationDisabledReason={detail.values.implementationDisabledReason}
                />
            )

            expect(screen.queryByTestId('inbox-report-create-pr')).not.toBeInTheDocument()
            await user.click(screen.getByTestId('inbox-report-open-task'))

            expect(capture).toHaveBeenCalledWith(
                'Inbox report action',
                expect.objectContaining({
                    action_type: 'implementation_button_clicked',
                    surface: 'detail_pane',
                    button_action: 'view_task',
                    button_position: 'header',
                }),
                undefined
            )
            expect(createPrFromReport).not.toHaveBeenCalled()
            expect(runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).values.activeCreation).toMatchObject({
                taskId: task.id,
                runId: task.latest_run.id,
            })
            detail.unmount()
        }
    )

    it.each([200, 503])('keeps customer prompts available without GitHub access (status %i)', async (status) => {
        let repositoryStatus = status
        useMocks({
            get: {
                '/api/projects/:team_id/signals/onboarding/': {
                    draft: null,
                    completed_at: null,
                    github_optional_available: true,
                },
                '/api/projects/:team_id/integrations/': { results: [{ id: 1, kind: 'github' }], next: null },
                '/api/projects/:team_id/integrations/1/github_repository_access/': () => [
                    repositoryStatus,
                    { available: false },
                ],
                '/api/projects/:team_id/integrations/github/available_installations/': {
                    installations: [],
                    personal_github_connected: false,
                },
            },
        })
        const user = userEvent.setup()
        const report = makeReport()
        render(<ImplementButton report={report} />)
        const access = reportGithubAccessLogic({ report })
        await waitFor(() => expect(access.values[status === 503 ? 'failed' : 'repairNeeded']).toBe(true))
        await user.click(screen.getByTestId('inbox-report-create-pr-steer'))
        await user.click(screen.getByTestId('inbox-report-copy-implementation-prompt'))
        expect(copyToClipboard).toHaveBeenCalledWith(
            expect.stringContaining('report ID: report-1'),
            'prompt for your agent'
        )
        expect(createPrFromReport).not.toHaveBeenCalled()
        if (status === 503) {
            expect(screen.getByTestId('inbox-report-create-pr-submit')).toHaveAttribute('aria-disabled', 'true')
            repositoryStatus = 200
            await user.click(screen.getByText('Retry GitHub check'))
            await waitFor(() => expect(access.values.repairNeeded).toBe(true))
        }
        await user.click(screen.getByTestId('inbox-report-create-pr-submit'))
        expect(await screen.findByText('Manage on GitHub')).toBeInTheDocument()
        expect(createPrFromReport).not.toHaveBeenCalled()
    })

    it.each([
        [
            'the PostHog button',
            (user: ReturnType<typeof userEvent.setup>) =>
                user.click(screen.getByTestId('inbox-report-create-pr-submit')),
        ],
        ['Enter', (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Enter}')],
    ])('passes steering instructions with %s', async (_method, submit) => {
        const capture = jest.spyOn(posthog, 'capture')
        jest.mocked(captureInboxReportAction).mockImplementation(
            jest.requireActual('../../inboxAnalytics').captureInboxReportAction
        )
        const user = await openMenu()

        await user.type(
            screen.getByPlaceholderText('Add instructions for the PostHog agent (optional)'),
            '  Keep the existing API  '
        )
        await submit(user)

        await waitFor(() =>
            expect(createPrFromReport).toHaveBeenCalledWith(
                expect.objectContaining({ id: 'report-1' }),
                'Keep the existing API'
            )
        )
        expect(
            capture.mock.calls.filter(([, properties]) => properties?.action_type === 'implementation_button_clicked')
        ).toEqual([
            [
                'Inbox report action',
                expect.objectContaining({
                    action_type: 'implementation_button_clicked',
                    surface: 'detail_pane',
                    button_action: 'implement',
                    button_position: 'body',
                }),
                undefined,
            ],
        ])
        expect(
            jest.mocked(captureInboxReportAction).mock.calls.find(([event]) => event.actionType === 'create_pr')?.[0]
                .extra
        ).toEqual({
            has_feedback: true,
            claim_step: 'start',
            opened_from_link: false,
        })
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
        await user.click(screen.getByText('Claude Code CLI'))

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
})
