import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_FLAT_TAB_LIST_PARAMS, reportListLogic } from '../logics/reportListLogic'
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
        render(
            <InboxReportList
                tabKey="reports"
                listParams={INBOX_FLAT_TAB_LIST_PARAMS.reports}
                Card={StubCard}
                emptyState={{ content: <div>empty</div> }}
            />
        )

        await screen.findByText('Report page-1')
        // The sentinel only enters the DOM after the first page lands, so the observer has to
        // attach then — not on mount, when there is nothing to observe.
        await waitFor(() => expect(intersectObservedElement).not.toBeNull())

        act(() => intersectObservedElement!())

        await screen.findByText('Report page-2')
        expect(requestedOffsets).toEqual(['0', '1'])
    })

    it('holds the empty state for a settled-zero tab while its list loads', async () => {
        // The tab bar's `FlatTabCount` settles a tab's badge count to zero before it is opened. When
        // the tab then mounts, the count is a known zero while the list request is still in flight.
        // The tab is known-empty, so it must show the empty state — never blank into a 0-card
        // skeleton for the length of that request.
        let releaseList: () => void = () => {}
        const listHeld = new Promise<void>((resolve) => {
            releaseList = resolve
        })
        const emptyPage = { count: 0, next: null, previous: null, results: [] }
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                '/api/projects/:team_id/signals/reports/': async ({ request }) => {
                    const { searchParams } = new URL(request.url)
                    // The badge count (`limit=1`) settles at zero right away.
                    if (searchParams.get('limit') === '1') {
                        return [200, emptyPage]
                    }
                    // Hold the list page so the mid-load render (list in flight, count already 0) is
                    // observable rather than settling past.
                    await listHeld
                    return [200, emptyPage]
                },
            },
        })

        render(
            <InboxReportList
                tabKey="reports"
                listParams={INBOX_FLAT_TAB_LIST_PARAMS.reports}
                Card={StubCard}
                emptyState={{ content: <div>empty</div> }}
            />
        )

        await screen.findByText('empty')

        // Release the held request and let it settle so nothing resolves after teardown.
        act(() => releaseList())
        await waitFor(() =>
            expect(
                reportListLogic({ tabKey: 'reports', listParams: INBOX_FLAT_TAB_LIST_PARAMS.reports }).values.isLoaded
            ).toBe(true)
        )
    })
})
