import { MOCK_DEFAULT_USER } from 'lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { FirstReportStateApi } from '../../../generated/api.schemas'
import { INBOX_EVENTS } from '../../inboxAnalytics'
import { inboxFiltersLogic } from '../../logics/inboxFiltersLogic'
import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { reportListLogic, sectionListLogicProps } from '../../logics/reportListLogic'
import { INBOX_SCOPE_ENTIRE_PROJECT, InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import { InboxStateFilter } from '../shell/InboxStateFilter'
import { ReportsTab } from './ReportsTab'

jest.mock('posthog-js')
// The filters, scope, and bulk bar each pull in their own endpoints; these tests are about what the
// flat list renders and reports as a whole. The row mock keeps a row and its state identifiable
// without the full card DOM.
jest.mock('../cards/ReportContextMenu', () => ({
    ReportContextMenu: ({ report, sectionKey }: { report: SignalReport; sectionKey: InboxReportSectionKey }) => (
        <div data-attr={`report-card-${report.id}`} data-section={sectionKey} />
    ),
}))
jest.mock('../shell/InboxReportFilters', () => ({ InboxReportFilters: () => null }))
jest.mock('../shell/InboxScopeFilter', () => ({ InboxScopeFilter: () => null }))
jest.mock('../shell/InboxBulkSelectionBar', () => ({ InboxBulkSelectionBar: () => null }))
jest.mock('products/posthog_ai/frontend/api/readableRun', () => ({
    ReadonlyRunSurface: (props: { taskId: string; runId: string; interaction: string }) => (
        <div aria-label="Scout activity" data-interaction={props.interaction}>
            {props.taskId}/{props.runId}
        </div>
    ),
}))

interface SectionCountStub {
    match: (params: URLSearchParams) => boolean
    count: number
}

// One count per state's fixed filter, so the summed total is unambiguous.
const COUNT_BY_FILTER: SectionCountStub[] = [
    { match: (p) => p.get('has_implementation_pr') === 'true', count: 4 },
    { match: (p) => p.get('view') === 'needs_decision', count: 7 },
    { match: (p) => p.get('view') === 'dismissed', count: 2 },
    { match: (p) => p.get('view') === 'held_back', count: 1 },
]

// Only `ready` + `not_actionable` reports: the pipeline's actionability judgment leaves the status
// alone, so nothing lands in the counted states.
const ONLY_NOT_ACTIONABLE: SectionCountStub[] = [
    { match: (p) => p.get('actionability') === 'not_actionable' && !p.has('has_implementation_pr'), count: 3 },
]

function mockReportCounts(stubs: SectionCountStub[]): void {
    useMocks({
        get: {
            '/api/projects/:team_id/signals/source_configs': { results: [] },
            '/api/projects/:team_id/signals/scout/configs': [],
            '/api/projects/:team_id/signals/reports/available_reviewers': {},
            '/api/projects/:team_id/signals/reports/': ({ request }) => {
                const params = new URL(request.url).searchParams
                const count = stubs.find((c) => c.match(params))?.count ?? 0
                return [200, { count, next: null, previous: null, results: [] }]
            },
        },
    })
}

function mockOnboarding(firstReport: FirstReportStateApi, notify: boolean): void {
    useMocks({
        get: {
            '/api/projects/:id/signals/onboarding/': {
                completed_at: new Date().toISOString(),
                draft: null,
                jobs: { scout: 'started', recommendations: 'skipped' },
                first_report: firstReport,
                first_report_completion_notification: true,
                first_report_notification_email: notify ? 'person@example.com' : null,
            },
            '/api/projects/:id/signals/scout/suggestions/': { status: 'idle', items: [], generated_at: null },
            '/api/projects/:id/vision/scanners/': { results: [], next: null },
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
    const failed = makeReport('failed', SignalReportStatus.FAILED)
    const resolved = makeReport('resolved', SignalReportStatus.RESOLVED)
    const closed = makeReport('closed', SignalReportStatus.CLOSED)
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
                        : params.get('view') === 'needs_decision'
                          ? [needsPr, failed]
                          : isResolved
                            ? [resolved]
                            : params.get('view') === 'closed'
                              ? [closed]
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

    it.each<[FirstReportStateApi['status'], string, boolean]>([
        ['pending', 'Checking your project', true],
        ['running', 'Looking for your first report', true],
        ['no_data', 'Waiting for your first report', true],
        ['no_data', 'Waiting for your first report', false],
        ['insufficient_data', 'More data is needed', true],
        ['no_actionable_finding', 'Your first investigation is complete', true],
        ['incomplete', 'Your first investigation couldn’t finish', true],
    ])('shows %s: %s (notifications: %s)', async (status, heading, notify) => {
        mockReportCounts([])
        mockOnboarding(
            {
                status,
                ...(['no_data', 'pending', 'incomplete'].includes(status)
                    ? {}
                    : { task_id: 'task-1', task_run_id: 'run-1' }),
            },
            notify
        )
        const { container } = render(<ReportsTab />)
        expect(await screen.findByText(heading)).toBeVisible()
        expect(container.querySelector('[data-attr="inbox-activation-explore"]')).toHaveAttribute(
            'aria-expanded',
            'false'
        )
        expect(screen.queryByText('Recommended for your product')).not.toBeInTheDocument()
        if (status === 'no_data') {
            expect(screen.queryByLabelText('Scout activity')).not.toBeInTheDocument()
            expect(screen.getByLabelText('Example report')).toBeVisible()
            expect(screen.getByText('Trial users cannot upgrade to Pro')).toBeVisible()
            expect(screen.queryByText('Connect a data source')).not.toBeInTheDocument()
        } else {
            expect(screen.queryByLabelText('Example report')).not.toBeInTheDocument()
            if (status !== 'pending' && status !== 'incomplete') {
                expect(screen.getByLabelText('Scout activity')).toHaveTextContent('task-1/run-1')
                expect(screen.getByLabelText('Scout activity')).toHaveAttribute('data-interaction', 'live')
            }
        }
        if (status === 'running') {
            expect(screen.getByText(/roughly 2½ minutes/)).toBeVisible()
        }
        if (notify) {
            expect(screen.getByText(/We’ll notify you when your first report is ready/)).toBeVisible()
        } else {
            expect(screen.queryByText(/We’ll notify you when your first report is ready/)).not.toBeInTheDocument()
        }
    })

    it.each<FirstReportStateApi['status']>(['running', 'insufficient_data'])(
        'hides %s progress when the current filters have reports',
        async (status) => {
            mockOnboarding({ status, task_id: 'task-1', task_run_id: 'run-1' }, true)
            mockReportRows()
            inboxFiltersLogic.mount()
            inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)
            inboxFiltersLogic.actions.setFilters({ ...inboxFiltersLogic.values, stateFilter: ['resolved'] })

            const { container } = render(<ReportsTab />)
            expect(container.querySelector('[data-attr="inbox-first-report-progress"]')).toBeNull()
            await waitFor(() => expect(container.querySelector('[data-attr="report-card-resolved"]')).not.toBeNull())
            expect(container.querySelector('[data-attr="inbox-first-report-progress"]')).toBeNull()

            inboxFiltersLogic.actions.setFilters({ ...inboxFiltersLogic.values, stateFilter: ['held-back'] })
            await waitFor(() =>
                expect(container.querySelector('[data-attr="inbox-first-report-progress"]')).not.toBeNull()
            )
            expect(container.querySelector('[data-attr="report-card-resolved"]')).toBeNull()

            inboxFiltersLogic.actions.setFilters({ ...inboxFiltersLogic.values, stateFilter: ['needs-decision'] })
            await waitFor(() => expect(container.querySelector('[data-attr="report-card-needs-pr"]')).not.toBeNull())
            expect(container.querySelector('[data-attr="inbox-first-report-progress"]')).toBeNull()
        }
    )

    // Polling flips the state while the card is on screen. The card has to go and the report has to
    // land in the list without a page reload.
    it.each(['none', 'rows', 'counts-and-rows'])(
        'replaces the first-report card with the report (refresh failure: %s)',
        async (refreshFailure) => {
            mockReportCounts([])
            mockOnboarding({ status: 'running', task_id: 'task-1', task_run_id: 'run-1' }, true)
            inboxFiltersLogic.mount()
            inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)

            const { container } = render(<ReportsTab />)
            expect(await screen.findByText('Looking for your first report')).toBeVisible()
            await waitFor(() =>
                expect(reportListLogic(sectionListLogicProps('needs-decision')).values.isLoaded).toBe(true)
            )

            const first = makeReport('first', SignalReportStatus.READY)
            let failRefresh = refreshFailure !== 'none'
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/': ({ request }) => {
                        const params = new URL(request.url).searchParams
                        if (
                            failRefresh &&
                            (refreshFailure === 'counts-and-rows' || params.get('count_only') !== 'true')
                        ) {
                            return [503, { detail: 'Reports temporarily unavailable' }]
                        }
                        const results = params.get('view') === 'needs_decision' ? [first] : []
                        return [200, { count: results.length, next: null, previous: null, results }]
                    },
                },
            })
            mockOnboarding(
                { status: 'report_created', task_id: 'task-1', task_run_id: 'run-1', report_id: first.id },
                true
            )
            inboxSetupLogic.actions.loadSetup()

            if (failRefresh) {
                const retry = await screen.findByText('Retry')
                expect(container.querySelector('[data-attr="inbox-first-report-progress"]')).toBeNull()
                failRefresh = false
                fireEvent.click(retry)
            }
            await waitFor(() => expect(document.querySelector('[data-attr="report-card-first"]')).not.toBeNull())
            expect(screen.queryByText('Retry')).not.toBeInTheDocument()
            expect(container.querySelector('[data-attr="inbox-first-report-progress"]')).toBeNull()
            expect(screen.queryByText('Your first report is ready')).toBeNull()
        }
    )

    // `Inbox viewed` fires once every count has settled, so it doubles as "the empty verdict is in".
    async function waitForCountsToSettle(): Promise<void> {
        await waitFor(() => {
            const viewed = (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === INBOX_EVENTS.VIEWED)
            expect(viewed).toHaveLength(1)
        })
    }

    // All the states load at once, so the naive wiring fires one `Inbox viewed` per state and
    // multiplies every visit in the activation funnel.
    it.each([
        { name: 'the visible sections', counts: COUNT_BY_FILTER, total: 14, empty: false },
        {
            name: 'only Closed reports',
            counts: [{ match: (params: URLSearchParams) => params.get('view') === 'closed', count: 3 }],
            total: 3,
            empty: false,
        },
    ])('fires Inbox viewed once for $name', async ({ counts, total, empty }) => {
        mockReportCounts(counts)
        render(<ReportsTab />)

        await waitFor(() => {
            const viewed = (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === INBOX_EVENTS.VIEWED)
            expect(viewed).toHaveLength(1)
            expect(viewed[0][1]).toMatchObject({ tab: 'reports', total_count: total, is_empty: empty })
        })
    })

    // The empty verdict must cover every state the current user can see, not only the counted
    // ones: a staff user on a project whose reports are all judged not actionable still has work
    // to review, so the waiting state would be wrong for them and right for everyone else.
    it.each([
        {
            name: 'staff does not see the waiting state when only Not actionable has reports',
            isStaff: true,
            empty: false,
        },
        { name: 'non-staff sees the empty state for the same project', isStaff: false, empty: true },
    ])('$name', async ({ isStaff, empty }) => {
        mockReportCounts(ONLY_NOT_ACTIONABLE)
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)

        render(<ReportsTab />)
        await waitForCountsToSettle()

        expect(screen.queryByText('Your agents are working in the background') !== null).toBe(empty)
    })

    // A search or scope that matches nothing must keep the filter controls available so the user
    // can get back to the full list.
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
        expect(screen.queryByText('Your agents are working in the background')).toBeNull()
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
            expect(document.querySelector('[data-attr="report-card-failed"]')).toHaveAttribute(
                'data-section',
                'needs-decision'
            )
        })
        expect(document.querySelector('[data-attr="report-card-resolved"]')).toBeNull()
        expect(document.querySelector('[data-attr="report-card-closed"]')).toBeNull()

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
            expect(document.querySelector('[data-attr="report-card-failed"]')).toBeNull()
        })
        expect(document.querySelector('[data-attr="report-card-with-pr"]')).not.toBeNull()

        inboxFiltersLogic.actions.setFilters({ ...inboxFiltersLogic.values, stateFilter: [] })
        await waitFor(() =>
            expect(document.querySelector('[data-attr="report-card-closed"]')).toHaveAttribute('data-section', 'closed')
        )

        inboxFiltersLogic.actions.setFilters({ ...inboxFiltersLogic.values, stateFilter: ['closed'] })
        await waitFor(() => expect(document.querySelector('[data-attr="report-card-with-pr"]')).toBeNull())
        expect(document.querySelector('[data-attr="report-card-closed"]')).not.toBeNull()
    })

    it.each([0, 2])('offers Closed only when the project has closed reports (%s)', async (count) => {
        mockReportCounts([
            {
                match: (params) =>
                    params.get('view') === 'closed' && !params.has('search') && !params.has('suggested_reviewers'),
                count,
            },
        ])
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setSearchQuery('no matching reports')
        render(<InboxStateFilter />)

        await waitFor(() =>
            expect(reportListLogic(sectionListLogicProps('closed')).values.hasProjectClosedReports).toBe(count > 0)
        )
        fireEvent.click(screen.getByText('2 statuses'))
        expect(screen.queryByText('Closed') !== null).toBe(count > 0)
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
            createdWindow: null,
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
