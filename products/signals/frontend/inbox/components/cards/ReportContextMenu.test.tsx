import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../../types'
import { ReportContextMenu } from './ReportContextMenu'

jest.mock('posthog-js')
jest.mock('lib/utils/copyToClipboard')

const BROWSER_LINK_ROWS = ['Open link', 'Open link in new tab', 'Copy link']

function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id: 'report-1',
        title: 'Report one',
        summary: 'summary',
        status: SignalReportStatus.READY,
        actionability: 'immediately_actionable',
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
        ...overrides,
    }
}

function openMenu(report: SignalReport): void {
    render(
        <ReportContextMenu report={report} sectionKey="needs-decision">
            <div data-attr="row">{report.title}</div>
        </ReportContextMenu>
    )
    fireEvent.contextMenu(screen.getByText(report.title!))
}

function menuRowText(): (string | null)[] {
    return screen.queryAllByRole('menuitem').map((item) => item.textContent)
}

describe('ReportContextMenu', () => {
    let stateRequests: { reportId: string; body: Record<string, unknown> }[]
    let overrideRequests: { reportId: string; body: Record<string, unknown> }[]
    let createdTasks: Record<string, unknown>[]

    beforeEach(() => {
        stateRequests = []
        overrideRequests = []
        createdTasks = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/signals/reports/:report_id/artefacts/': {
                    count: 1,
                    results: [
                        {
                            id: 'artefact-1',
                            type: 'safety_judgment',
                            content: { choice: false, explanation: "Unsafe instruction in the report's signals." },
                            created_at: '2026-06-11T10:00:00Z',
                        },
                    ],
                },
            },
            post: {
                '/api/projects/:team_id/signals/reports/:report_id/state/': async ({ request, params }) => {
                    stateRequests.push({
                        reportId: params.report_id as string,
                        body: (await request.json()) as Record<string, unknown>,
                    })
                    return [200, {}]
                },
                '/api/projects/:team_id/signals/reports/:report_id/safety_override/': async ({ request, params }) => {
                    overrideRequests.push({
                        reportId: params.report_id as string,
                        body: (await request.json()) as Record<string, unknown>,
                    })
                    return [200, { id: params.report_id, status: 'ready' }]
                },
                '/api/projects/:team_id/tasks/': async ({ request }) => {
                    createdTasks.push((await request.json()) as Record<string, unknown>)
                    return [201, { id: 'task-1' }]
                },
                '/api/projects/:team_id/tasks/:task_id/run/': { id: 'run-1' },
            },
        })
        initKeaTests()
    })

    // The menu content renders in a portal, so cleanup keeps one case's rows out of the next.
    afterEach(cleanup)

    // The menu must mirror the detail pane's eligibility rules; a drifted guard silently offers a
    // dead-end action (a 409 transition, a duplicate PR) or hides a legitimate one. Every menu
    // also carries the browser link actions the trigger suppresses on the row's native menu.
    it.each([
        {
            name: 'a ready actionable report offers every action',
            report: makeReport(),
            expected: ['Select', 'Create PR', 'Resolve', 'Dismiss', 'Reviewers'],
        },
        {
            name: 'a report with a PR does not offer creating another',
            report: makeReport({ implementation_pr_url: 'https://github.com/posthog/posthog/pull/1' }),
            expected: ['Select', 'Resolve', 'Dismiss', 'Reviewers'],
        },
        {
            name: 'an in-progress report cannot be resolved yet',
            report: makeReport({ status: SignalReportStatus.IN_PROGRESS, actionability: null }),
            expected: ['Select', 'Dismiss', 'Reviewers'],
        },
        {
            name: 'a dismissed report offers restore, and creating a PR anyway',
            report: makeReport({ status: SignalReportStatus.SUPPRESSED }),
            expected: ['Select', 'Create PR', 'Restore'],
        },
        // The statuses PostHog declined to implement from. Create PR is offered behind a
        // confirmation; the verdict submenus stay hidden because those transitions still 409.
        {
            name: 'an unresearched report offers creating a PR anyway',
            report: makeReport({ status: SignalReportStatus.POTENTIAL, actionability: null }),
            expected: ['Select', 'Create PR', 'Dismiss', 'Reviewers'],
        },
        {
            name: 'a failed report offers creating a PR anyway',
            report: makeReport({ status: SignalReportStatus.FAILED, actionability: null }),
            expected: ['Select', 'Create PR', 'Dismiss', 'Reviewers'],
        },
        // The product's own reading is that this report holds no work, which is a different claim
        // from "we would not risk it" — so the escape hatch does not apply to it.
        {
            name: 'a not-actionable dismissed report offers only restore',
            report: makeReport({ status: SignalReportStatus.SUPPRESSED, actionability: 'not_actionable' }),
            expected: ['Select', 'Restore'],
        },
    ])('$name', ({ report, expected }) => {
        openMenu(report)

        expect(menuRowText()).toEqual([...expected, ...BROWSER_LINK_ROWS])
    })

    // A relative or wrong-tab URL would copy a link that 404s or opens the wrong list when pasted.
    it('copies the absolute report detail link', () => {
        openMenu(makeReport())

        fireEvent.click(screen.getByText('Copy link'))

        expect(jest.mocked(copyToClipboard)).toHaveBeenCalledWith('http://localhost/inbox/reports/report-1', 'link')
    })

    // Terminal rows must keep the browser's own context menu rather than an empty custom one.
    it.each([
        { name: 'a resolved report', report: makeReport({ status: SignalReportStatus.RESOLVED }) },
        {
            name: 'a refunded dismissed report',
            report: makeReport({
                status: SignalReportStatus.SUPPRESSED,
                // The menu only checks refund presence, so the row's other fields don't matter here.
                refund: { id: 'refund-1' } as unknown as SignalReport['refund'],
            }),
        },
    ])('renders no menu for $name', ({ report }) => {
        openMenu(report)

        expect(menuRowText()).toEqual([])
    })

    // The submenu's whole point: a reason click persists that reason, with no dialog in the way.
    // A miswired option (wrong state, wrong reason value) would silently record the wrong verdict on
    // every report. The immediate catch-all action uses "Other" without an ellipsis so it does not
    // imply that a dialog will open.
    it.each([
        {
            submenu: 'Resolve',
            reason: 'PR was merged',
            body: { state: 'resolved', dismissal_reason: 'pr_merged' },
        },
        {
            submenu: 'Resolve',
            reason: 'Other',
            body: { state: 'resolved', dismissal_reason: 'other' },
        },
        {
            submenu: 'Dismiss',
            reason: "Won't fix - intentional behavior",
            body: { state: 'suppressed', dismissal_reason: 'wontfix_intentional' },
        },
        {
            submenu: 'Dismiss',
            reason: 'Other',
            body: { state: 'suppressed', dismissal_reason: 'other' },
        },
    ])('$submenu > $reason applies through the state API', async ({ submenu, reason, body }) => {
        openMenu(makeReport())

        fireEvent.click(screen.getByText(submenu))
        fireEvent.click(await screen.findByText(reason))

        await waitFor(() => {
            expect(stateRequests).toEqual([{ reportId: 'report-1', body }])
        })
    })

    // Two reasons still need the dialog: an instant wrong-repo dismissal would record the mistake
    // without the corrected repository, which is the half of the feedback the next repo selection
    // learns from, and the pencil beside "Something else…" is the only way left to write a note.
    it.each([
        {
            name: 'the wrong repository reason',
            submenu: 'Dismiss',
            pick: 'Agent picked the wrong repository',
            byLabel: false,
            dialog: 'Dismiss report "Report one"?',
        },
        {
            name: "the dismiss submenu's note button",
            submenu: 'Dismiss',
            // The pencil carries no label text of its own, so it answers to its tooltip.
            pick: 'Dismiss and write a note',
            byLabel: true,
            dialog: 'Dismiss report "Report one"?',
        },
        {
            name: "the resolve submenu's note button",
            submenu: 'Resolve',
            pick: 'Resolve and write a note',
            byLabel: true,
            dialog: 'Resolve report "Report one"?',
        },
    ])('routes $name through the dialog instead of applying it', async ({ submenu, pick, byLabel, dialog }) => {
        openMenu(makeReport())

        fireEvent.click(screen.getByText(submenu))
        fireEvent.click(byLabel ? await screen.findByLabelText(pick) : await screen.findByText(pick))

        expect(await screen.findByText(dialog)).toBeInTheDocument()
        expect(stateRequests).toEqual([])
    })

    // Create PR on a report PostHog declined to implement must state the reason and wait, and the
    // person's decision has to be recorded before a run exists — without the recorded override the
    // merged PR would leave the report sitting where the safety judge left it.
    it('routes Create PR on a blocked report through the confirmation', async () => {
        openMenu(makeReport({ status: SignalReportStatus.SUPPRESSED }))

        fireEvent.click(screen.getByText('Create PR'))

        expect(await screen.findByText('Implement "Report one" anyway?')).toBeInTheDocument()
        expect(await screen.findByText(/Unsafe instruction in the report's signals/)).toBeInTheDocument()
        expect(overrideRequests).toEqual([])
        expect(createdTasks).toEqual([])
    })

    it('records the override and starts the run once the person confirms', async () => {
        openMenu(makeReport({ status: SignalReportStatus.SUPPRESSED }))

        fireEvent.click(screen.getByText('Create PR'))
        fireEvent.click(await screen.findByText('Implement anyway'))

        await waitFor(() => {
            expect(overrideRequests).toEqual([{ reportId: 'report-1', body: {} }])
        })
        await waitFor(() => {
            expect(createdTasks).toHaveLength(1)
        })
    })
})
