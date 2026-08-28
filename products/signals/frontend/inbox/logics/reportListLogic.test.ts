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
import {
    INBOX_REPORT_SECTION_LIST_PARAMS,
    reportListLogic,
    SECTION_PAGE_SIZE,
    shouldDefaultToEntireProject,
} from './reportListLogic'

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
            // Only the primary section (Needs a PR) drives the default.
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

    // A section shows a short window over a much larger server page, so "Show more" has two jobs
    // that are easy to get wrong in opposite directions: widening the window, and reaching for the
    // next server page only once the window has outrun the rows already in hand.
    describe('section paging window', () => {
        // Two full sections' worth on the first page, so the first press is served from memory.
        const FIRST_PAGE = Array.from({ length: SECTION_PAGE_SIZE * 2 }, (_, i) => makeReport(`page-1-${i}`))
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

        it('shows one section-worth of the loaded page', () => {
            expect(logic.values.visibleReports).toHaveLength(SECTION_PAGE_SIZE)
            expect(logic.values.hiddenReportCount).toBe(FIRST_PAGE.length + SECOND_PAGE.length - SECTION_PAGE_SIZE)
        })

        it('widens the window from rows already loaded, without a new request', async () => {
            logic.actions.showMore()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.visibleReports).toHaveLength(SECTION_PAGE_SIZE * 2)
            expect(requestedOffsets).toEqual(['0'])
        })

        it('fetches the next page once the window outruns the loaded rows', async () => {
            logic.actions.showMore()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.showMore()
            await expectLogic(logic).toFinishAllListeners()

            expect(requestedOffsets).toEqual(['0', String(FIRST_PAGE.length)])
            expect(logic.values.reports).toHaveLength(FIRST_PAGE.length + SECOND_PAGE.length)
        })

        // "Show more" widens the window past the loaded rows before the next page lands, so a failed
        // next-page request leaves the window ahead of the loaded rows. The hidden count must track
        // the rows on screen, not the window size — otherwise it hits zero and unmounts the only
        // control that can retry, stranding the unfetched rows.
        it('keeps Show more after a failed next-page request so the rows stay reachable', async () => {
            useMocks({
                get: {
                    [REPORTS_URL]: ({ request }) => {
                        const offset = new URL(request.url).searchParams.get('offset')
                        return offset && offset !== '0'
                            ? [500, {}]
                            : [
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
            // First press is served from memory; the second outruns the loaded rows and the
            // next-page fetch fails.
            logic.actions.showMore()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.showMore()
            await expectLogic(logic).toFinishAllListeners()

            // The second page never arrived, so the loaded rows are unchanged...
            expect(logic.values.reports).toHaveLength(FIRST_PAGE.length)
            expect(logic.values.visibleReports).toHaveLength(FIRST_PAGE.length)
            // ...but the section still knows one report is held back and offers to fetch it again.
            expect(logic.values.hiddenReportCount).toBe(SECOND_PAGE.length)
        })
    })
})
