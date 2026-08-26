/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxReportSectionsLogic } from '../logics/inboxReportSectionsLogic'
import { SignalReportStatus } from '../types'
import { InboxReportSection } from './InboxReportSection'

// The card and the impression log are unrelated to when rows are fetched, and both pull in the
// whole inbox scene.
jest.mock('./cards/ReportCard', () => ({
    ReportCard: ({ report }: { report: { id: string; title: string } }) => <div>{report.title}</div>,
}))
jest.mock('./useReportImpressions', () => ({ useReportImpressions: () => undefined }))

describe('InboxReportSection', () => {
    let pageRequests: number

    beforeEach(() => {
        // Section expand/collapse persists to localStorage, which initKeaTests does not clear — wipe
        // it so each test starts from the default open/closed state rather than a prior test's toggle.
        localStorage.clear()
        pageRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    // The header count is a separate count-only request, and a collapsed section is
                    // still entitled to make it.
                    if (new URL(request.url).searchParams.get('limit') !== '1') {
                        pageRequests += 1
                    }
                    return [
                        200,
                        {
                            count: 1,
                            next: null,
                            previous: null,
                            results: [
                                {
                                    id: 'r1',
                                    title: 'A report',
                                    summary: 'summary',
                                    status: SignalReportStatus.READY,
                                    total_weight: 0,
                                    signal_count: 1,
                                    relevant_user_count: null,
                                    artefact_count: 0,
                                    is_suggested_reviewer: false,
                                    created_at: '2026-06-11T10:00:00Z',
                                    updated_at: '2026-06-11T10:00:00Z',
                                },
                            ],
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    // Four sections render at once. If a collapsed one loaded its rows anyway, every visit would
    // pull a full page per section for content nobody asked to see.
    it('loads rows only once the section is expanded', async () => {
        // Resolved starts collapsed.
        render(<InboxReportSection sectionKey="resolved" />)

        await screen.findByText('Resolved')
        expect(screen.queryByText('A report')).not.toBeInTheDocument()
        expect(pageRequests).toBe(0)

        inboxReportSectionsLogic.findMounted()?.actions.toggleSection('resolved')

        await screen.findByText('A report')
        await waitFor(() => expect(pageRequests).toBe(1))
    })

    // A failed first fetch leaves `reportsResponse` null, so the section used to skeleton forever with
    // no way to recover. It must show a retry instead.
    it('shows a retry instead of a stuck skeleton when the first fetch fails', async () => {
        let failPage = true
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    // The header count is a separate request that keeps working.
                    if (new URL(request.url).searchParams.get('limit') === '1') {
                        return [200, { count: 1, next: null, previous: null, results: [] }]
                    }
                    if (failPage) {
                        return [500, {}]
                    }
                    return [
                        200,
                        {
                            count: 1,
                            next: null,
                            previous: null,
                            results: [
                                {
                                    id: 'r1',
                                    title: 'A report',
                                    summary: 'summary',
                                    status: SignalReportStatus.READY,
                                    total_weight: 0,
                                    signal_count: 1,
                                    relevant_user_count: null,
                                    artefact_count: 0,
                                    is_suggested_reviewer: false,
                                    created_at: '2026-06-11T10:00:00Z',
                                    updated_at: '2026-06-11T10:00:00Z',
                                },
                            ],
                        },
                    ]
                },
            },
        })

        render(<InboxReportSection sectionKey="resolved" />)
        await screen.findByText('Resolved')
        inboxReportSectionsLogic.findMounted()?.actions.toggleSection('resolved')

        // The failed load surfaces a retry, not a permanent skeleton.
        await screen.findByText("Couldn't load these reports.")

        // Retrying now succeeds and the row lands, clearing the error.
        failPage = false
        fireEvent.click(screen.getByText('Retry'))

        await screen.findByText('A report')
        expect(screen.queryByText("Couldn't load these reports.")).not.toBeInTheDocument()
    })
})
