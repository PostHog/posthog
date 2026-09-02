import { MOCK_DEFAULT_USER } from 'lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_EVENTS } from '../../inboxAnalytics'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import { ReportsTab } from './ReportsTab'

jest.mock('posthog-js')
// The filters, scope, and bulk bar each pull in their own endpoints; these tests are about what the
// flat list renders and reports as a whole. The card mock keeps a row identifiable without the full
// card DOM.
jest.mock('../cards/ReportCard', () => ({
    ReportCard: ({ report, sectionKey }: { report: SignalReport; sectionKey: InboxReportSectionKey }) => (
        <div data-attr={`report-card-${report.id}`} data-section={sectionKey} />
    ),
}))
jest.mock('../shell/InboxReportFilters', () => ({ InboxReportFilters: () => null }))
jest.mock('../shell/InboxScopeFilter', () => ({ InboxScopeFilter: () => null }))
jest.mock('../shell/InboxBulkSelectionBar', () => ({ InboxBulkSelectionBar: () => null }))
jest.mock('../SelfDrivingInstallingHint', () => ({ SelfDrivingInstallingHint: () => null }))

interface SectionCountStub {
    match: (params: URLSearchParams) => boolean
    count: number
}

// One count per state's fixed filter, so the summed total is unambiguous.
const COUNT_BY_FILTER: SectionCountStub[] = [
    { match: (p) => p.get('has_implementation_pr') === 'true', count: 4 },
    { match: (p) => p.get('has_implementation_pr') === 'false', count: 7 },
    { match: (p) => (p.get('status') ?? '').includes('suppressed'), count: 2 },
]

// Only `ready` + `not_actionable` reports: the pipeline's actionability judgment leaves the status
// alone, so nothing lands in the counted states.
const ONLY_NOT_ACTIONABLE: SectionCountStub[] = [
    { match: (p) => p.get('actionability') === 'not_actionable' && !p.has('has_implementation_pr'), count: 3 },
]

function mockReportCounts(stubs: SectionCountStub[]): void {
    useMocks({
        get: {
            '/api/projects/:team_id/signals/reports/available_reviewers': {},
            '/api/projects/:team_id/signals/reports/': ({ request }) => {
                const params = new URL(request.url).searchParams
                const count = stubs.find((c) => c.match(params))?.count ?? 0
                return [200, { count, next: null, previous: null, results: [] }]
            },
        },
    })
}

function makeReport(id: string, status: SignalReportStatus): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

// Rows keyed off each state's fixed filter, so which state contributed a row is observable. The
// optional gate holds the Resolved state's rows response (not its `limit=1` count) open, so a test
// can assert what the list shows while that state is still loading its first page.
function mockReportRows(resolvedRowsGate?: { block: Promise<void>; onRequest: () => void }): void {
    const withPr = makeReport('with-pr', SignalReportStatus.READY)
    const needsPr = makeReport('needs-pr', SignalReportStatus.READY)
    const resolved = makeReport('resolved', SignalReportStatus.RESOLVED)
    useMocks({
        get: {
            '/api/projects/:team_id/signals/reports/available_reviewers': {},
            '/api/projects/:team_id/signals/reports/': async ({ request }) => {
                const params = new URL(request.url).searchParams
                const isResolved = (params.get('status') ?? '').includes('resolved')
                if (isResolved && params.get('limit') !== '1' && resolvedRowsGate) {
                    resolvedRowsGate.onRequest()
                    await resolvedRowsGate.block
                }
                const results =
                    params.get('has_implementation_pr') === 'true'
                        ? [withPr]
                        : params.get('has_implementation_pr') === 'false'
                          ? [needsPr]
                          : isResolved
                            ? [resolved]
                            : []
                return [200, { count: results.length, next: null, previous: null, results }]
            },
        },
    })
}

describe('ReportsTab', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
        // The filters persist to localStorage, so one test's toggles must not leak into the next.
        localStorage.clear()
        mockReportCounts(COUNT_BY_FILTER)
        initKeaTests()
    })

    afterEach(cleanup)

    // `Inbox viewed` fires once every count has settled, so it doubles as "the empty verdict is in".
    async function waitForCountsToSettle(): Promise<void> {
        await waitFor(() => {
            const viewed = (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === INBOX_EVENTS.VIEWED)
            expect(viewed).toHaveLength(1)
        })
    }

    // All the states load at once, so the naive wiring fires one `Inbox viewed` per state and
    // multiplies every visit in the activation funnel.
    it('fires Inbox viewed once for the whole list', async () => {
        render(<ReportsTab />)

        await waitFor(() => {
            const viewed = (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === INBOX_EVENTS.VIEWED)
            expect(viewed).toHaveLength(1)
            // Needs decision + Review and merge + Resolved + Dismissed. Not actionable is staff-only triage.
            expect(viewed[0][1]).toMatchObject({ tab: 'reports', total_count: 13, is_empty: false })
        })
    })

    // The empty verdict must cover every state the current user can see, not only the counted
    // ones: a staff user on a project whose reports are all judged not actionable still has work
    // to review, so "nothing yet" would be wrong for them and right for everyone else.
    it.each([
        { name: 'staff is not told "nothing yet" when only Not actionable has reports', isStaff: true, empty: false },
        { name: 'non-staff sees the empty state for the same project', isStaff: false, empty: true },
    ])('$name', async ({ isStaff, empty }) => {
        mockReportCounts(ONLY_NOT_ACTIONABLE)
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)

        render(<ReportsTab />)
        await waitForCountsToSettle()

        expect(screen.queryByText('Nothing in your inbox yet') !== null).toBe(empty)
    })

    // "Nothing yet" claims the project has no reports. A search or scope that matches nothing must
    // not make that claim, or the user loses the way back to the full list.
    it.each([
        {
            name: 'a search that matches nothing',
            setUp: () => inboxFiltersLogic.actions.setSearchQuery('zzz'),
            copy: 'No reports match the current filters.',
        },
        {
            name: 'the For-you scope',
            setUp: () => inboxFiltersLogic.actions.setScope('for-you'),
            copy: 'No reports suggested for you yet. Switch the scope to see the entire project.',
        },
    ])('keeps the filter-aware copy when $name is active', async ({ setUp, copy }) => {
        mockReportCounts([])
        inboxFiltersLogic.mount()
        setUp()

        render(<ReportsTab />)
        await waitForCountsToSettle()

        await waitFor(() => expect(screen.getByText(copy)).toBeInTheDocument())
        expect(screen.queryByText('Nothing in your inbox yet')).toBeNull()
    })

    // The whole point of the flat list: one merged run over the selected states. The default
    // selection is the open work (Review and merge + Needs decision); the state filter widens it
    // to the closed states and narrows it back down.
    it('shows the open-work states by default and follows the state filter', async () => {
        let releaseResolvedRows: () => void = () => {}
        let resolvedRowsRequested = false
        mockReportRows({
            block: new Promise((resolve) => {
                releaseResolvedRows = resolve
            }),
            onRequest: () => {
                resolvedRowsRequested = true
            },
        })
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)

        render(<ReportsTab />)

        await waitFor(() => {
            expect(document.querySelector('[data-attr="report-card-with-pr"]')).not.toBeNull()
            expect(document.querySelector('[data-attr="report-card-needs-pr"]')).not.toBeNull()
        })
        expect(document.querySelector('[data-attr="report-card-resolved"]')).toBeNull()

        inboxFiltersLogic.actions.toggleState('resolved')

        // The loaded rows must stay on screen while the newly selected state fetches its first
        // page: falling back to the first-load skeleton here wipes the list on every state toggle.
        await waitFor(() => expect(resolvedRowsRequested).toBe(true))
        expect(document.querySelector('[data-attr="report-card-with-pr"]')).not.toBeNull()
        expect(document.querySelector('[data-attr="report-card-needs-pr"]')).not.toBeNull()

        releaseResolvedRows()
        await waitFor(() => {
            expect(document.querySelector('[data-attr="report-card-resolved"]')).not.toBeNull()
        })

        inboxFiltersLogic.actions.toggleState('needs-decision')

        await waitFor(() => {
            expect(document.querySelector('[data-attr="report-card-needs-pr"]')).toBeNull()
        })
        expect(document.querySelector('[data-attr="report-card-with-pr"]')).not.toBeNull()
    })

    // A shared link or persisted storage can carry `state=not-actionable`, a staff-only state the
    // filter control offers no checkbox for. If it narrowed the list for a non-staff user, they
    // would be stuck on an empty view with no way to clear it.
    it('does not trap a non-staff user on a staff-only state filter', async () => {
        mockReportRows()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: false })
        inboxFiltersLogic.mount()
        // A shared link carrying only the staff-only state, hydrated the way urlToAction applies it.
        inboxFiltersLogic.actions.setFilters({
            scope: INBOX_SCOPE_ENTIRE_PROJECT,
            sourceProductFilter: [],
            scoutFilter: [],
            priorityFilter: [],
            stateFilter: ['not-actionable'],
            sortField: 'priority',
            sortDirection: 'asc',
            searchQuery: '',
        })

        render(<ReportsTab />)

        await waitFor(() => {
            expect(document.querySelector('[data-attr="report-card-with-pr"]')).not.toBeNull()
            expect(document.querySelector('[data-attr="report-card-needs-pr"]')).not.toBeNull()
            expect(document.querySelector('[data-attr="report-card-resolved"]')).not.toBeNull()
        })
        expect(screen.queryByText('No reports match the current filters.')).toBeNull()
    })
})
