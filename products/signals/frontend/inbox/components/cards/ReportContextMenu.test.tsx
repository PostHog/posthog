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

    beforeEach(() => {
        stateRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': { count: 0, next: null, previous: null, results: [] },
            },
            post: {
                '/api/projects/:team_id/signals/reports/:report_id/state/': async ({ request, params }) => {
                    stateRequests.push({
                        reportId: params.report_id as string,
                        body: (await request.json()) as Record<string, unknown>,
                    })
                    return [200, {}]
                },
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
            expected: ['Create PR', 'Resolve', 'Dismiss', 'Reviewers'],
        },
        {
            name: 'a report with a PR does not offer creating another',
            report: makeReport({ implementation_pr_url: 'https://github.com/posthog/posthog/pull/1' }),
            expected: ['Resolve', 'Dismiss', 'Reviewers'],
        },
        {
            name: 'an in-progress report cannot be resolved yet',
            report: makeReport({ status: SignalReportStatus.IN_PROGRESS, actionability: null }),
            expected: ['Dismiss', 'Reviewers'],
        },
        {
            name: 'a dismissed report only offers restore',
            report: makeReport({ status: SignalReportStatus.SUPPRESSED }),
            expected: ['Restore'],
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

    // The submenu's whole point: a reason click persists that reason. A miswired option (wrong
    // state, wrong reason value) would silently record the wrong verdict on every report.
    it('resolves with the picked reason through the state API', async () => {
        openMenu(makeReport())

        fireEvent.click(screen.getByText('Resolve'))
        fireEvent.click(await screen.findByText('PR was merged'))

        await waitFor(() => {
            expect(stateRequests).toEqual([
                { reportId: 'report-1', body: { state: 'resolved', dismissal_reason: 'pr_merged' } },
            ])
        })
    })

    it('dismisses with the picked reason through the state API', async () => {
        openMenu(makeReport())

        fireEvent.click(screen.getByText('Dismiss'))
        fireEvent.click(await screen.findByText("Won't fix - intentional behavior"))

        await waitFor(() => {
            expect(stateRequests).toEqual([
                { reportId: 'report-1', body: { state: 'suppressed', dismissal_reason: 'wontfix_intentional' } },
            ])
        })
    })

    // An instant wrong-repo dismissal would record the mistake without the corrected repository,
    // which is the half of the feedback the next repo selection learns from.
    it('routes the wrong repository reason through the dialog instead of applying it', async () => {
        openMenu(makeReport())

        fireEvent.click(screen.getByText('Dismiss'))
        fireEvent.click(await screen.findByText('Agent picked the wrong repository'))

        expect(await screen.findByText('Dismiss report "Report one"?')).toBeInTheDocument()
        expect(stateRequests).toEqual([])
    })
})
