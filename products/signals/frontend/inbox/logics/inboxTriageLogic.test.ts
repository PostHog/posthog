/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SignalReport, SignalReportStatus } from '../types'
import { inboxTriageLogic } from './inboxTriageLogic'

const REPORTS_URL = '/api/projects/:team_id/signals/reports/'
// Matches the list logic's server page size, so a spot past it needs a second page.
const PAGE_SIZE = 50

function makeReport(id: string, extra: Partial<SignalReport> = {}): SignalReport {
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
        ...extra,
    } satisfies SignalReport
}

const REVIEW_REPORTS = Array.from({ length: 2 }, (_, i) =>
    makeReport(`pr-${i}`, { implementation_pr_url: `https://github.com/example/app/pull/${i + 1}` })
)

const FIRST_PAGE = Array.from({ length: PAGE_SIZE }, (_, i) => makeReport(`r-${i}`))
const SECOND_PAGE = Array.from({ length: 10 }, (_, i) => makeReport(`r-${PAGE_SIZE + i}`))

describe('inboxTriageLogic', () => {
    let requestedOffsets: (string | null)[]
    let logic: ReturnType<typeof inboxTriageLogic.build>

    beforeEach(() => {
        requestedOffsets = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                [REPORTS_URL]: ({ request }) => {
                    const { searchParams } = new URL(request.url)
                    // The Review-and-merge list stays empty unless a test overrides it, so the
                    // Needs-a-PR queue keeps its indexes.
                    if (searchParams.get('has_implementation_pr') === 'true') {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    const offset = searchParams.get('offset')
                    if (searchParams.get('limit') !== '1') {
                        requestedOffsets.push(offset)
                    }
                    const firstPage = offset === '0' || offset === null
                    return [
                        200,
                        {
                            count: FIRST_PAGE.length + SECOND_PAGE.length,
                            next: firstPage
                                ? `http://localhost/api/projects/997/signals/reports/?offset=${PAGE_SIZE}`
                                : null,
                            previous: null,
                            results: firstPage ? FIRST_PAGE : SECOND_PAGE,
                        },
                    ]
                },
            },
        })
        initKeaTests()
        // Triage mode is a redesign surface: with the flag off the scene redirects its URL to the list.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_REDESIGN], {
            [FEATURE_FLAGS.INBOX_REDESIGN]: true,
        })
    })

    afterEach(() => logic?.unmount())

    async function mountAt(searchParams: Record<string, unknown>): Promise<void> {
        router.actions.push(urls.inboxTriage(), searchParams)
        logic = inboxTriageLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it.each([
        {
            name: 'lands on the report the URL names',
            searchParams: { report: 'r-7', at: 7 },
            expectedId: 'r-7',
            expectedOffsets: ['0'],
        },
        {
            name: 'prefers the report over a stale index when rows above it were archived',
            searchParams: { report: 'r-7', at: 9 },
            expectedId: 'r-7',
            expectedOffsets: ['0'],
        },
        {
            name: 'falls back to the index when the report is no longer in the queue',
            searchParams: { report: 'gone', at: 3 },
            expectedId: 'r-3',
            expectedOffsets: ['0'],
        },
        {
            name: 'pages forward until a spot past the first page is loaded',
            searchParams: { report: `r-${PAGE_SIZE + 5}`, at: PAGE_SIZE + 5 },
            expectedId: `r-${PAGE_SIZE + 5}`,
            expectedOffsets: ['0', String(PAGE_SIZE)],
        },
    ])('$name', async ({ searchParams, expectedId, expectedOffsets }) => {
        await mountAt(searchParams)

        expect(logic.values.currentReport?.id).toBe(expectedId)
        expect(logic.values.isRestoringPosition).toBe(false)
        expect(requestedOffsets).toEqual(expectedOffsets)
    })

    // Restoring to a spot past the first page means paging forward; if that page request fails, the
    // view must stop waiting and show the nearest loaded report instead of skeletons forever.
    it('stops restoring and shows the nearest loaded report when the next page fails', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                [REPORTS_URL]: ({ request }) => {
                    const { searchParams } = new URL(request.url)
                    if (searchParams.get('has_implementation_pr') === 'true') {
                        return [200, { count: 0, next: null, previous: null, results: [] }]
                    }
                    if (searchParams.get('limit') === '1') {
                        return [
                            200,
                            { count: FIRST_PAGE.length + SECOND_PAGE.length, next: null, previous: null, results: [] },
                        ]
                    }
                    const offset = searchParams.get('offset')
                    if (offset === '0' || offset === null) {
                        return [
                            200,
                            {
                                count: FIRST_PAGE.length + SECOND_PAGE.length,
                                next: `http://localhost/api/projects/997/signals/reports/?offset=${PAGE_SIZE}`,
                                previous: null,
                                results: FIRST_PAGE,
                            },
                        ]
                    }
                    return [500, {}]
                },
            },
        })

        await mountAt({ report: `r-${PAGE_SIZE + 5}`, at: PAGE_SIZE + 5 })

        // The remembered spot's page never arrived, so the view falls back to the last loaded report
        // rather than staying on the restoring skeleton.
        expect(logic.values.isRestoringPosition).toBe(false)
        expect(logic.values.currentReport?.id).toBe(`r-${PAGE_SIZE - 1}`)
    })

    // A failed first load leaves the response null, so `isLoaded` never flips; the view keys the
    // retry off `reportsLoadFailed` instead of skeletoning forever.
    it('flags a failed initial load instead of loading forever', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/available_reviewers': {},
                [REPORTS_URL]: () => [500, {}],
            },
        })

        await mountAt({})

        expect(logic.values.isLoaded).toBe(false)
        expect(logic.values.reportsLoadFailed).toBe(true)
    })

    describe('with pull requests to review', () => {
        let stateCalls: { reportId: string; state: string }[]

        beforeEach(() => {
            stateCalls = []
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/available_reviewers': {},
                    [REPORTS_URL]: ({ request }) => {
                        const { searchParams } = new URL(request.url)
                        const forReview = searchParams.get('has_implementation_pr') === 'true'
                        const results = forReview
                            ? REVIEW_REPORTS
                            : FIRST_PAGE.slice(0, 3).map((report) => ({
                                  ...report,
                                  actionability: 'immediately_actionable' as const,
                              }))
                        return [200, { count: results.length, next: null, previous: null, results }]
                    },
                },
                post: {
                    '/api/projects/:team_id/signals/reports/:reportId/state': async ({ request, params }) => {
                        const body = (await request.json()) as { state: string }
                        stateCalls.push({ reportId: String(params.reportId), state: body.state })
                        return [200, {}]
                    },
                },
            })
        })

        it('walks the pull requests to review before the reports that need one', async () => {
            await mountAt({})

            expect(logic.values.reports.map((report) => report.id)).toEqual(['pr-0', 'pr-1', 'r-0', 'r-1', 'r-2'])
            expect(logic.values.currentSectionKey).toBe('monitoring')
            expect(logic.values.currentPrUrl).toBe('https://github.com/example/app/pull/1/files')
            expect(logic.values.canCreatePr).toBe(false)

            logic.actions.navigate(2)
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.currentReport?.id).toBe('r-0')
            expect(logic.values.currentSectionKey).toBe('needs-decision')
            expect(logic.values.currentPrUrl).toBeNull()
            expect(logic.values.canCreatePr).toBe(true)
        })

        // Archiving must hit the list that owns the row, or the row lingers in the queue and the
        // spot never moves on.
        it('archives a pull request through its own list and moves to the next spot', async () => {
            await mountAt({})

            logic.actions.reviewArchiveReport('pr-0', 'already_fixed', '')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.reports.map((report) => report.id)).toEqual(['pr-1', 'r-0', 'r-1', 'r-2'])
            expect(logic.values.currentReport?.id).toBe('pr-1')
            expect(router.values.searchParams).toEqual({ report: 'pr-1', at: 0 })
            expect(stateCalls).toEqual([{ reportId: 'pr-0', state: 'suppressed' }])
        })
    })

    it('keeps the URL on the current spot and hands it to the report page as the way back', async () => {
        await mountAt({})
        logic.actions.navigate(1)
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.location.pathname.endsWith(urls.inboxTriage())).toBe(true)
        expect(router.values.searchParams).toEqual({ report: 'r-1', at: 1 })
        expect(logic.values.currentReportUrl).toBe(
            `/inbox/reports/r-1?back=${encodeURIComponent('/inbox/reports/triage?report=r-1&at=1')}`
        )
    })
})
