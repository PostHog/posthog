/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_EVENTS } from '../../inboxAnalytics'
import { ReportsTab } from './ReportsTab'

jest.mock('posthog-js')
// The sections, filters, and bulk bar each pull in their own endpoints; this is about what the tab
// reports for the list as a whole.
jest.mock('../InboxReportSection', () => ({ InboxReportSection: () => null }))
jest.mock('../shell/InboxReportFilters', () => ({ InboxReportFilters: () => null }))
jest.mock('../shell/InboxBulkSelectionBar', () => ({ InboxBulkSelectionBar: () => null }))

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

describe('ReportsTab', () => {
    beforeEach(() => {
        ;(posthog.capture as jest.Mock).mockClear()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const count = COUNT_BY_FILTER.find((c) => c.match(params))?.count ?? 0
                    return [200, { count, next: null, previous: null, results: [] }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

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
})
