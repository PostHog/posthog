import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { legacyTabListLogicProps, reportListLogic } from '../logics/reportListLogic'
import { SignalReport, SignalReportStatus } from '../types'
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

    it('shows an error with retry when the first page fails, and recovers on retry', async () => {
        let firstPageAttempts = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    const { searchParams } = new URL(request.url)
                    // The badge count request must still succeed — a non-zero count is what used to
                    // hold the skeleton up forever once the page load failed.
                    if (searchParams.get('limit') === '1') {
                        return [200, { count: 5, next: null, previous: null, results: [] }]
                    }
                    firstPageAttempts += 1
                    if (firstPageAttempts === 1) {
                        return [500, { detail: 'boom' }]
                    }
                    return [200, { count: 5, next: null, previous: null, results: [makeReport('recovered')] }]
                },
            },
        })

        render(<InboxReportList tabKey="reports" Card={StubCard} emptyState={{ content: <div>empty</div> }} />)

        const retry = await screen.findByText('Retry')
        expect(screen.getByText("Couldn't load these reports.")).toBeInTheDocument()

        act(() => retry.click())

        await screen.findByText('Report recovered')
        expect(screen.queryByText("Couldn't load these reports.")).not.toBeInTheDocument()
    })

    it('retry refetches when a refresh fails on an already-loaded empty list', async () => {
        let pageAttempts = 0
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    const { searchParams } = new URL(request.url)
                    if (searchParams.get('limit') === '1') {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    pageAttempts += 1
                    // First load lands empty (a tab or filter with no matches), the refresh fails,
                    // then the retry recovers. A failed load keeps the earlier empty response, so
                    // `ensureLoaded` alone would send no request — the retry must refetch.
                    if (pageAttempts === 1) {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    if (pageAttempts === 2) {
                        return [500, { detail: 'boom' }]
                    }
                    return [200, { count: 1, next: null, previous: null, results: [makeReport('recovered')] }]
                },
            },
        })

        render(<InboxReportList tabKey="reports" Card={StubCard} emptyState={{ content: <div>empty</div> }} />)

        await screen.findByText('empty')
        // A reload (filter/scope change, bulk broadcast) refetches the loaded list and fails here.
        act(() => reportListLogic(legacyTabListLogicProps('reports')).actions.refresh())

        const retry = await screen.findByText('Retry')
        expect(screen.getByText("Couldn't load these reports.")).toBeInTheDocument()

        act(() => retry.click())

        await screen.findByText('Report recovered')
        expect(screen.queryByText("Couldn't load these reports.")).not.toBeInTheDocument()
    })
})
