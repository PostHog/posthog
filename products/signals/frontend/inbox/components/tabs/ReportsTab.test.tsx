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
import { INBOX_SCOPE_ENTIRE_PROJECT } from '../../types'
import { ReportsTab } from './ReportsTab'

jest.mock('posthog-js')
// The sections, filters, and bulk bar each pull in their own endpoints; this is about what the tab
// reports for the list as a whole.
jest.mock('../InboxReportSection', () => ({
    InboxReportSection: ({ sectionKey }: { sectionKey: string }) => <div data-attr={`section-${sectionKey}`} />,
}))
jest.mock('../shell/InboxReportFilters', () => ({ InboxReportFilters: () => null }))
jest.mock('../shell/InboxBulkSelectionBar', () => ({ InboxBulkSelectionBar: () => null }))
jest.mock('../SelfDrivingInstallingHint', () => ({ SelfDrivingInstallingHint: () => null }))

interface SectionCountStub {
    match: (params: URLSearchParams) => boolean
    count: number
}

// One count per section's fixed filter, so the summed total is unambiguous.
const COUNT_BY_FILTER: SectionCountStub[] = [
    { match: (p) => p.get('has_implementation_pr') === 'true', count: 4 },
    { match: (p) => p.get('has_implementation_pr') === 'false', count: 7 },
    { match: (p) => (p.get('status') ?? '').includes('suppressed'), count: 2 },
]

// Only `ready` + `not_actionable` reports: the pipeline's actionability judgment leaves the status
// alone, so nothing lands in the three counted sections.
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

describe('ReportsTab', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
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

    // The sections all render at once, so the naive wiring fires one `Inbox viewed` per section and
    // triples every visit in the activation funnel.
    it('fires Inbox viewed once for the whole list', async () => {
        render(<ReportsTab />)

        await waitFor(() => {
            const viewed = (posthog.capture as jest.Mock).mock.calls.filter(([event]) => event === INBOX_EVENTS.VIEWED)
            expect(viewed).toHaveLength(1)
            // Needs a PR + Review and merge + Resolved. Not actionable is staff-only triage.
            expect(viewed[0][1]).toMatchObject({ tab: 'reports', total_count: 13, is_empty: false })
        })
    })

    // The empty verdict used to be taken over the three counted sections only, so a staff user on a
    // project whose reports were all judged not actionable was told "nothing yet" while the section
    // built to review them was never mounted.
    it.each([
        { name: 'staff sees Not actionable when it is the only section with reports', isStaff: true, empty: false },
        { name: 'non-staff sees the empty state for the same project', isStaff: false, empty: true },
    ])('$name', async ({ isStaff, empty }) => {
        mockReportCounts(ONLY_NOT_ACTIONABLE)
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, is_staff: isStaff })
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)

        render(<ReportsTab />)
        await waitForCountsToSettle()

        expect(screen.queryByText('Nothing in your inbox yet') !== null).toBe(empty)
        expect(document.querySelector('[data-attr="section-not-actionable"]') !== null).toBe(!empty)
    })

    // "Nothing yet" claims the project has no reports. A search or scope that matches nothing must
    // not make that claim, or the user loses the filter bar's own per-section feedback.
    it.each([
        { name: 'a search that matches nothing', setUp: () => inboxFiltersLogic.actions.setSearchQuery('zzz') },
        { name: 'the For-you scope', setUp: () => inboxFiltersLogic.actions.setScope('for-you') },
    ])('keeps the sections when $name is active', async ({ setUp }) => {
        mockReportCounts([])
        inboxFiltersLogic.mount()
        setUp()

        render(<ReportsTab />)
        await waitForCountsToSettle()

        expect(document.querySelector('[data-attr="section-needs-decision"]')).not.toBeNull()
        expect(screen.queryByText('Nothing in your inbox yet')).toBeNull()
    })
})
