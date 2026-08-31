import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { inboxFiltersLogic } from '../logics/inboxFiltersLogic'
import { INBOX_SCOPE_FOR_YOU, SignalReport, SignalReportStatus } from '../types'
import { InboxReportList, InboxReportCardProps } from './InboxReportList'

// The list chrome is unrelated to paging and pulls in its own scout/filter endpoints.
jest.mock('./shell/InboxSearchFilterBar', () => ({ InboxSearchFilterBar: () => null }))
jest.mock('./shell/InboxBulkSelectionBar', () => ({ InboxBulkSelectionBar: () => null }))

/** Fires whatever the component handed to `IntersectionObserver.observe`, as if it scrolled into view. */
let intersectObservedElement: (() => void) | null = null

function StubCard({ report }: InboxReportCardProps): JSX.Element {
    return <div>{report.title}</div>
}

function makeReport(id: string): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        relevant_user_count: null,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

describe('InboxReportList', () => {
    let requestedOffsets: (string | null)[]
    let listIsEmpty: boolean

    beforeAll(() => {
        // jsdom has no IntersectionObserver; the infinite-scroll sentinel needs one.
        global.IntersectionObserver = class {
            constructor(private callback: IntersectionObserverCallback) {}
            observe(): void {
                intersectObservedElement = () =>
                    this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as any)
            }
            unobserve(): void {}
            disconnect(): void {}
        } as unknown as typeof IntersectionObserver
    })

    beforeEach(() => {
        intersectObservedElement = null
        requestedOffsets = []
        listIsEmpty = false
        // Filter state is persisted, so a filter one case sets would otherwise carry into the next.
        localStorage.clear()
        useMocks({
            get: {
                // Reviewer scope loads alongside the list; an empty map keeps it out of the way.
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    const { searchParams } = new URL(request.url)
                    const offset = searchParams.get('offset')
                    const limit = searchParams.get('limit')
                    // The tab badge fires a separate count-only request; don't count it as a page.
                    if (limit !== '1') {
                        requestedOffsets.push(offset)
                    }
                    if (listIsEmpty) {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    const page = offset === '0' || offset === null ? '1' : '2'
                    return [
                        200,
                        {
                            count: 277,
                            // A non-null `next` is what tells the list there are more pages.
                            next: 'http://localhost/api/projects/997/signals/reports/?offset=50',
                            previous: null,
                            results: [makeReport(`page-${page}`)],
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    it('keeps paging once the sentinel scrolls into view', async () => {
        render(<InboxReportList tabKey="reports" Card={StubCard} emptyState={{ content: <div>empty</div> }} />)

        await screen.findByText('Report page-1')
        // The sentinel only enters the DOM after the first page lands, so the observer has to
        // attach then — not on mount, when there is nothing to observe.
        await waitFor(() => expect(intersectObservedElement).not.toBeNull())

        act(() => intersectObservedElement!())

        await screen.findByText('Report page-2')
        expect(requestedOffsets).toEqual(['0', '1'])
    })

    it('blames the filter when a narrowed list is empty, instead of the tab copy', async () => {
        // The tab's own copy claims the project has nothing of this kind. On a filtered zero-row
        // response it tells the user their inbox is empty when it is not, with no hint that a
        // filter is what emptied it and no way to clear it.
        listIsEmpty = true
        inboxFiltersLogic.mount()
        inboxFiltersLogic.actions.setFilters({
            scope: INBOX_SCOPE_FOR_YOU,
            sourceProductFilter: [],
            scoutFilter: [],
            priorityFilter: ['P1'],
            sortField: 'priority',
            sortDirection: 'asc',
            searchQuery: '',
        })

        render(<InboxReportList tabKey="reports" Card={StubCard} emptyState={{ content: <div>No reports yet</div> }} />)

        expect(await screen.findByText('No reports match this view')).toBeInTheDocument()
        expect(screen.getByText('Clear filters')).toBeInTheDocument()
        expect(screen.queryByText('No reports yet')).not.toBeInTheDocument()
    })
})
