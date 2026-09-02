/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    InboxReportSectionKey,
    InboxScope,
    SignalReport,
    SignalReportStatus,
} from '../types'
import { INBOX_REPORT_SECTION_LIST_PARAMS, reportListLogic, shouldDefaultToEntireProject } from './reportListLogic'

const REPORTS_URL = '/api/projects/:team_id/signals/reports/'

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

describe('reportListLogic', () => {
    describe('shouldDefaultToEntireProject', () => {
        const base = {
            sectionKey: 'needs-decision' as InboxReportSectionKey,
            primarySectionKey: 'needs-decision' as InboxReportSectionKey,
            scope: INBOX_SCOPE_FOR_YOU as InboxScope,
            hasUserChosenScope: false,
            hasResolvedUser: true,
            count: 0 as number | null,
        }

        it('switches to Entire project when a fresh user has zero assigned reports', () => {
            expect(shouldDefaultToEntireProject(base)).toBe(true)
        })

        // With the redesign flag off the Pull requests list is the primary section instead.
        it('keys the switch on whichever section the layout treats as primary', () => {
            const legacy = { ...base, primarySectionKey: 'monitoring' as InboxReportSectionKey }
            expect(shouldDefaultToEntireProject({ ...legacy, sectionKey: 'monitoring' })).toBe(true)
            expect(shouldDefaultToEntireProject({ ...legacy, sectionKey: 'needs-decision' })).toBe(false)
        })

        it.each<[string, Partial<typeof base>]>([
            // The user has reports assigned – keep them on For you.
            ['user has assigned reports', { count: 3 }],
            // The user deliberately picked a scope – never override it, even with zero reports.
            ['user chose their scope', { hasUserChosenScope: true }],
            // Only the primary section (Needs decision) drives the default.
            ['not the primary section', { sectionKey: 'monitoring' as InboxReportSectionKey }],
            // Already off For you – nothing to default.
            ['already entire project', { scope: INBOX_SCOPE_ENTIRE_PROJECT as InboxScope }],
            // Count for For-you scope is only meaningful once the user's uuid has resolved.
            ['user not resolved yet', { hasResolvedUser: false }],
            // Count request in flight / failed (null) is not treated as "zero".
            ['count not loaded', { count: null }],
        ])('stays put when %s', (_label, override) => {
            expect(shouldDefaultToEntireProject({ ...base, ...override })).toBe(false)
        })
    })

    // The flat list pages every state through `loadMore`, so it must append from the loaded offset
    // and stay quiet once the server says there is nothing further.
    describe('list paging', () => {
        const FIRST_PAGE = Array.from({ length: 10 }, (_, i) => makeReport(`page-1-${i}`))
        const SECOND_PAGE = [makeReport('page-2-0')]
        let requestedOffsets: (string | null)[]
        let logic: ReturnType<typeof reportListLogic.build>

        beforeEach(async () => {
            requestedOffsets = []
            useMocks({
                get: {
                    // Reviewer scope loads alongside the list; an empty map keeps it out of the way.
                    '/api/projects/:team_id/signals/reports/available_reviewers': {},
                    [REPORTS_URL]: ({ request }) => {
                        const { searchParams } = new URL(request.url)
                        const offset = searchParams.get('offset')
                        // The header count fires a separate count-only request; not a page.
                        if (searchParams.get('limit') !== '1') {
                            requestedOffsets.push(offset)
                        }
                        const firstPage = offset === '0' || offset === null
                        return [
                            200,
                            {
                                count: FIRST_PAGE.length + SECOND_PAGE.length,
                                // A non-null `next` is what tells the section there are more pages.
                                next: firstPage ? 'http://localhost/api/projects/997/signals/reports/?offset=50' : null,
                                previous: null,
                                results: firstPage ? FIRST_PAGE : SECOND_PAGE,
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            logic = reportListLogic({
                sectionKey: 'needs-decision',
                listParams: INBOX_REPORT_SECTION_LIST_PARAMS['needs-decision'],
            })
            logic.mount()
            logic.actions.ensureLoaded()
            await expectLogic(logic).toFinishAllListeners()
        })

        afterEach(() => logic.unmount())

        it('appends the next server page from the loaded offset, then stops', async () => {
            logic.actions.loadMore()
            await expectLogic(logic).toFinishAllListeners()

            expect(requestedOffsets).toEqual(['0', String(FIRST_PAGE.length)])
            expect(logic.values.reports).toHaveLength(FIRST_PAGE.length + SECOND_PAGE.length)

            // The second page came back with `next: null`, so a further loadMore fires no request.
            logic.actions.loadMore()
            await expectLogic(logic).toFinishAllListeners()
            expect(requestedOffsets).toEqual(['0', String(FIRST_PAGE.length)])
        })

        // A failed next page keeps the loaded rows and `hasMore`, and the scroll sentinel may sit
        // inside the viewport without re-firing. The flag is what surfaces the retry control, and a
        // plain `loadMore` must be able to fetch the page again.
        it('flags a failed next page and clears the flag on a successful retry', async () => {
            let failNextPage = true
            useMocks({
                get: {
                    [REPORTS_URL]: ({ request }) => {
                        const offset = new URL(request.url).searchParams.get('offset')
                        if (offset && offset !== '0') {
                            if (failNextPage) {
                                failNextPage = false
                                return [500, {}]
                            }
                            return [
                                200,
                                {
                                    count: FIRST_PAGE.length + SECOND_PAGE.length,
                                    next: null,
                                    previous: null,
                                    results: SECOND_PAGE,
                                },
                            ]
                        }
                        return [
                            200,
                            {
                                count: FIRST_PAGE.length + SECOND_PAGE.length,
                                next: 'http://localhost/api/projects/997/signals/reports/?offset=50',
                                previous: null,
                                results: FIRST_PAGE,
                            },
                        ]
                    },
                },
            })

            logic.actions.loadMore()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pageLoadFailed).toBe(true)
            expect(logic.values.reports).toHaveLength(FIRST_PAGE.length)

            logic.actions.loadMore()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.pageLoadFailed).toBe(false)
            expect(logic.values.reports).toHaveLength(FIRST_PAGE.length + SECOND_PAGE.length)
        })
    })
})
