import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../../types'
import { ReportVerdictButtons } from './ReportVerdictButtons'

jest.mock('posthog-js')

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

describe('ReportVerdictButtons', () => {
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

    // The menus render in a portal, so cleanup keeps one case's rows out of the next.
    afterEach(cleanup)

    // The row is the busiest place a report is judged from, and its whole promise is that a reason
    // lands on one more click. A menu wired to the wrong verdict, or back to the dialog, breaks that
    // silently — the row still looks right.
    it.each([
        {
            verdict: 'Resolve',
            reason: 'PR was merged',
            body: { state: 'resolved', dismissal_reason: 'pr_merged' },
        },
        {
            verdict: 'Dismiss',
            reason: 'Something else…',
            body: { state: 'suppressed', dismissal_reason: 'other' },
        },
    ])('$verdict > $reason applies through the state API', async ({ verdict, reason, body }) => {
        render(<ReportVerdictButtons report={makeReport()} sectionKey="needs-decision" />)

        fireEvent.click(screen.getByText(verdict))
        fireEvent.click(await screen.findByText(reason))

        await waitFor(() => {
            expect(stateRequests).toEqual([{ reportId: 'report-1', body }])
        })
    })

    // Resolve follows the backend's transition guard: offering it on a report that can't resolve
    // yet turns one click into a 409. Dismiss has no such limit and stays on every open row.
    it.each([
        { status: SignalReportStatus.READY, resolvable: true },
        { status: SignalReportStatus.PENDING_INPUT, resolvable: true },
        { status: SignalReportStatus.CANDIDATE, resolvable: false },
        { status: SignalReportStatus.FAILED, resolvable: false },
    ])('offers Resolve on a $status report: $resolvable', ({ status, resolvable }) => {
        render(<ReportVerdictButtons report={makeReport({ status })} sectionKey="needs-decision" />)

        expect(screen.queryByText('Resolve') !== null).toBe(resolvable)
        expect(screen.queryByText('Dismiss')).not.toBeNull()
    })
})
