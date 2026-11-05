import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { myAgentClaim, myClaim, teammateClaim } from '../../__mocks__/inboxMocks'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, SignalReport, SignalReportStatus } from '../../types'
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
    let claimRequests: { reportId: string; body: Record<string, unknown> }[]

    beforeEach(() => {
        stateRequests = []
        claimRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { count: 0, next: null, previous: null, results: [] },
                // The menu mounts logics that load these. Without a valid answer the loaders log errors, and
                // Jest formats those stack traces synchronously, which blocks waitFor long enough to time out.
                '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                '/api/projects/:team_id/signals/scout/configs/': [],
            },
            post: {
                '/api/projects/:team_id/signals/reports/:report_id/state/': async ({ request, params }) => {
                    stateRequests.push({
                        reportId: params.report_id as string,
                        body: (await request.json()) as Record<string, unknown>,
                    })
                    return [200, {}]
                },
                '/api/projects/:team_id/signals/reports/:report_id/claim/': async ({ request, params }) => {
                    claimRequests.push({
                        reportId: params.report_id as string,
                        body: (await request.json()) as Record<string, unknown>,
                    })
                    return [200, { id: params.report_id, assignee: myClaim, updated_at: '2026-06-11T11:00:00Z' }]
                },
            },
        })
        initKeaTests()
    })

    // The menu content renders in a portal, so cleanup keeps one case's rows out of the next.
    // The verdict dialogs mount a separate React root on document.body. cleanup does not remove it.
    afterEach(() => {
        cleanup()
        document.body.innerHTML = ''
    })

    // The menu must mirror the detail pane's eligibility rules; a drifted guard silently offers a
    // dead-end action (a 409 transition, a duplicate PR) or hides a legitimate one. Every menu
    // also carries the browser link actions the trigger suppresses on the row's native menu.
    it.each([
        {
            name: 'a ready actionable report offers every action',
            report: makeReport(),
            expected: ['Select', 'Claim', 'Create PR', 'Resolve', 'Dismiss', 'Reviewers', 'Remove yourself'],
        },
        {
            name: 'a report with a PR does not offer creating another',
            report: makeReport({ implementation_pr_url: 'https://github.com/posthog/posthog/pull/1' }),
            expected: ['Select', 'Claim', 'Resolve', 'Dismiss', 'Reviewers', 'Remove yourself'],
        },
        {
            name: 'an in-progress report cannot be resolved yet',
            report: makeReport({ status: SignalReportStatus.IN_PROGRESS, actionability: null }),
            expected: ['Select', 'Claim', 'Dismiss', 'Reviewers', 'Remove yourself'],
        },
        {
            name: 'a report the user claimed offers unclaim',
            report: makeReport({ assignee: myClaim }),
            expected: ['Select', 'Unclaim', 'Create PR', 'Resolve', 'Dismiss', 'Reviewers', 'Remove yourself'],
        },
        {
            name: 'a monitoring report nobody claimed cannot be claimed',
            report: makeReport({ status: SignalReportStatus.MONITORING }),
            expected: ['Select', 'Resolve', 'Dismiss', 'Reviewers', 'Remove yourself'],
        },
        {
            name: 'a dismissed report only offers restore',
            report: makeReport({ status: SignalReportStatus.SUPPRESSED }),
            expected: ['Select', 'Restore'],
        },
    ])('$name', ({ report, expected }) => {
        openMenu(report)

        expect(menuRowText()).toEqual([...expected, ...BROWSER_LINK_ROWS])
    })

    // Outside the "For me" scope, a report that does not name you must not offer to remove you from it.
    it.each([
        { name: 'names you', isReviewer: true, offered: true },
        { name: 'does not name you', isReviewer: false, offered: false },
    ])('in the whole-project scope, a report that $name', ({ isReviewer, offered }) => {
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)
        openMenu(makeReport({ is_suggested_reviewer: isReviewer }))

        expect(menuRowText().includes('Remove yourself')).toBe(offered)
    })

    // The menu closes on click, so the claim must go through the list logic, which outlives it.
    it.each([
        { name: 'claims an unclaimed report', report: makeReport(), item: 'Claim', body: { takeover: false } },
        {
            name: 'releases the user claim',
            report: makeReport({ assignee: myClaim }),
            item: 'Unclaim',
            body: { release: true },
        },
        {
            name: 'releases the claim made by the user through their agent',
            report: makeReport({ assignee: myAgentClaim }),
            item: 'Unclaim',
            body: { release: true },
        },
    ])('$name', async ({ report, item, body }) => {
        openMenu(report)

        fireEvent.click(screen.getByText(item))

        await waitFor(() => expect(claimRequests).toEqual([{ reportId: 'report-1', body }]))
    })

    // A 409 has two causes. Telling the user a teammate took the report when its status changed sends them
    // looking for a person who does not exist.
    it.each([
        {
            cause: 'a teammate claimed it',
            current: { assignee: teammateClaim, status: SignalReportStatus.READY },
            toast: 'Someone else is already working on this report.',
        },
        {
            cause: 'its status no longer allows a claim',
            current: { assignee: null, status: SignalReportStatus.RESOLVED },
            toast: 'This report changed. Check it and try again.',
        },
    ])('explains a refused claim when $cause', async ({ current, toast }) => {
        useMocks({
            get: { '/api/projects/:team_id/signals/reports/:report_id/': { ...makeReport(), ...current } },
            post: { '/api/projects/:team_id/signals/reports/:report_id/claim/': [409, {}] },
        })
        const errorToast = jest.spyOn(lemonToast, 'error')
        try {
            openMenu(makeReport())

            fireEvent.click(screen.getByText('Claim'))

            await waitFor(() => expect(errorToast).toHaveBeenCalledWith(toast))
        } finally {
            errorToast.mockRestore()
        }
    })

    it('does not let the user claim a report a teammate is working on', () => {
        openMenu(makeReport({ assignee: teammateClaim }))

        fireEvent.click(screen.getByText('Claim'))

        expect(claimRequests).toEqual([])
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
            reason: 'No action needed',
            body: { state: 'resolved', dismissal_reason: 'no_action_needed' },
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
        fireEvent.click(screen.getByText('Cancel'))
        await waitFor(() => expect(screen.queryByText(dialog)).not.toBeInTheDocument())
    })
})
