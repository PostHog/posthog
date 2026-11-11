/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { myClaim, teammateClaim } from '../__mocks__/inboxMocks'
import { openDismissReportDialog } from '../components/shell/DismissReportDialog'
import { openRemoveYourselfDialog } from '../components/shell/RemoveYourselfDialog'
import { openResolveReportDialog } from '../components/shell/ResolveReportDialog'
import { INBOX_SCOPE_ENTIRE_PROJECT, INBOX_SCOPE_FOR_YOU, SignalReport, SignalReportStatus } from '../types'
import { inboxFiltersLogic } from './inboxFiltersLogic'
import { inboxTriageLogic } from './inboxTriageLogic'

jest.mock('../components/shell/DismissReportDialog', () => ({ openDismissReportDialog: jest.fn() }))
jest.mock('../components/shell/ResolveReportDialog', () => ({ openResolveReportDialog: jest.fn() }))
// Confirms at once without a reason, so the navigation cases below exercise the removal itself.
jest.mock('../components/shell/RemoveYourselfDialog', () => ({
    openRemoveYourselfDialog: jest.fn(({ onConfirm }) => onConfirm(undefined)),
}))

const REPORTS_URL = '/api/projects/:team_id/signals/reports/'
// Matches the list logic's server page size, so a spot past it needs a second page.
const PAGE_SIZE = 50

function makeReport(id: string): SignalReport {
    return {
        id,
        title: `Report ${id}`,
        summary: 'summary',
        status: SignalReportStatus.READY,
        total_weight: 0,
        signal_count: 1,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: 'P2',
        source_products: ['error_tracking'],
        created_at: '2026-06-11T10:00:00Z',
        updated_at: '2026-06-11T10:00:00Z',
    } satisfies SignalReport
}

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
    })

    afterEach(() => {
        logic?.unmount()
        // The list scope persists to localStorage, so a test that changes it would leak into the next.
        localStorage.clear()
    })

    async function mountAt(searchParams: Record<string, unknown>): Promise<void> {
        router.actions.push(urls.inboxTriage(), searchParams)
        logic = inboxTriageLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    it('warns that triage closes an open PR on a failed report', async () => {
        const report = {
            ...makeReport('failed-with-pr'),
            status: SignalReportStatus.FAILED,
            pull_requests: [{ id: 'pr', url: 'https://github.com/example/repo/pull/1', state: 'open', merged: false }],
        }
        useMocks({
            get: {
                [REPORTS_URL]: { count: 1, next: null, previous: null, results: [report] },
            },
        })
        await mountAt({ report: report.id, at: 0 })
        logic.actions.resolveCurrent()
        logic.actions.dismissCurrent()
        expect(openResolveReportDialog).toHaveBeenCalledWith(expect.objectContaining({ hasOpenPr: true }))
        expect(openDismissReportDialog).toHaveBeenCalledWith(expect.objectContaining({ hasOpenPr: true }))
    })

    it.each([
        { scope: INBOX_SCOPE_FOR_YOU, mine: true, expectedId: 'r-3', stillQueued: false, unassigned: ['r-2'] },
        { scope: INBOX_SCOPE_ENTIRE_PROJECT, mine: true, expectedId: 'r-3', stillQueued: true, unassigned: ['r-2'] },
        { scope: INBOX_SCOPE_ENTIRE_PROJECT, mine: false, expectedId: 'r-2', stillQueued: true, unassigned: [] },
        { scope: INBOX_SCOPE_FOR_YOU, mine: false, expectedId: 'r-3', stillQueued: false, unassigned: ['r-2'] },
    ])(
        'unassigning me under $scope (reviewer: $mine) lands on $expectedId',
        async ({ scope, mine, expectedId, stillQueued, unassigned }) => {
            const reports = FIRST_PAGE.slice(0, 5).map((r) => ({ ...r, is_suggested_reviewer: mine }))
            const deleted: string[] = []
            useMocks({
                get: { [REPORTS_URL]: { count: reports.length, next: null, previous: null, results: reports } },
                delete: {
                    '/api/projects/:team_id/signals/reports/:id/reviewers/me/': ({ params }) => {
                        deleted.push(String(params.id))
                        return [204, null]
                    },
                },
            })
            await mountAt({ report: 'r-2', at: 2 })
            inboxFiltersLogic.actions.setScope(scope)
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.removeMeFromCurrent('hotkey')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.currentReport?.id).toBe(expectedId)
            expect(logic.values.reports.some((r) => r.id === 'r-2')).toBe(stillQueued)
            expect(deleted).toEqual(unassigned)
        }
    )

    it('sends the reason picked in the remove yourself dialog', async () => {
        jest.mocked(openRemoveYourselfDialog).mockImplementationOnce(({ onConfirm }) => onConfirm('wrong_area'))
        const reports = FIRST_PAGE.slice(0, 5).map((r) => ({ ...r, is_suggested_reviewer: true }))
        const bodies: unknown[] = []
        useMocks({
            get: { [REPORTS_URL]: { count: reports.length, next: null, previous: null, results: reports } },
            post: {
                '/api/projects/:team_id/signals/reports/:id/reviewers/me/': async ({ request }) => {
                    bodies.push(await request.json())
                    return [204, null]
                },
            },
        })
        await mountAt({ report: 'r-2', at: 2 })

        logic.actions.removeMeFromCurrent('hotkey')
        await expectLogic(logic).toFinishAllListeners()

        expect(bodies).toEqual([{ removal_reason: 'wrong_area' }])
    })

    it('sends one unassign request for the last report while the first one is pending', async () => {
        const report = { ...makeReport('last'), is_suggested_reviewer: true }
        const deleted: string[] = []
        let finishDelete: () => void = () => {}
        useMocks({
            get: { [REPORTS_URL]: { count: 1, next: null, previous: null, results: [report] } },
            delete: {
                '/api/projects/:team_id/signals/reports/:id/reviewers/me/': async ({ params }) => {
                    deleted.push(String(params.id))
                    await new Promise<void>((resolve) => (finishDelete = resolve))
                    return [204, null]
                },
            },
        })
        await mountAt({ report: report.id, at: 0 })
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.removeMeFromCurrent('hotkey')
        logic.actions.removeMeFromCurrent('hotkey')
        expect(logic.values.isRemovingMeFromCurrent).toBe(true)
        await waitFor(() => expect(deleted).toEqual(['last']))
        finishDelete()
        await expectLogic(logic).toFinishAllListeners()

        expect(deleted).toEqual(['last'])
        expect(logic.values.isRemovingMeFromCurrent).toBe(false)
    })

    it.each([
        {
            name: 'claims an unclaimed report',
            assignee: null,
            run: 'claim',
            bodies: [{ takeover: false }],
            reason: null,
        },
        { name: 'unclaims my report', assignee: 'me', run: 'unclaim', bodies: [{ release: true }], reason: null },
        {
            name: 'does not claim a report I already hold',
            assignee: 'me',
            run: 'claim',
            bodies: [],
            reason: "You can't claim this report in its current state",
        },
        { name: 'does not unclaim a report I do not hold', assignee: null, run: 'unclaim', bodies: [], reason: null },
        {
            name: "does not take over a teammate's claim",
            assignee: 'teammate',
            run: 'claim',
            bodies: [],
            reason: expect.stringContaining('Robin'),
        },
    ])('$name and stays on the report', async ({ assignee, run, bodies, reason }) => {
        const report = {
            ...makeReport('r-1'),
            assignee: assignee === 'me' ? myClaim : assignee === 'teammate' ? teammateClaim : null,
        }
        const received: unknown[] = []
        useMocks({
            get: { [REPORTS_URL]: { count: 2, next: null, previous: null, results: [report, makeReport('r-2')] } },
            post: {
                '/api/projects/:team_id/signals/reports/:id/claim/': async ({ request }) => {
                    received.push(await request.json())
                    return [200, { ...report, assignee: null }]
                },
            },
        })
        await mountAt({ report: report.id, at: 0 })

        if (run === 'claim') {
            logic.actions.claimCurrent('hotkey')
        } else {
            logic.actions.unclaimCurrent('hotkey')
        }
        await expectLogic(logic).toFinishAllListeners()

        expect(received).toEqual(bodies)
        expect(logic.values.currentReport?.id).toBe('r-1')
        expect(logic.values.claimDisabledReason).toEqual(reason)
    })

    it('loads the next page when unassigning me moves triage near the end of the loaded reports', async () => {
        const mine = (reports: SignalReport[]): SignalReport[] =>
            reports.map((r) => ({ ...r, is_suggested_reviewer: true }))
        useMocks({
            get: {
                [REPORTS_URL]: ({ request }) => {
                    const offset = new URL(request.url).searchParams.get('offset')
                    requestedOffsets.push(offset)
                    const firstPage = offset === '0' || offset === null
                    return [
                        200,
                        {
                            count: FIRST_PAGE.length + SECOND_PAGE.length,
                            next: firstPage
                                ? `http://localhost/api/projects/997/signals/reports/?offset=${PAGE_SIZE}`
                                : null,
                            previous: null,
                            results: mine(firstPage ? FIRST_PAGE : SECOND_PAGE),
                        },
                    ]
                },
            },
            delete: { '/api/projects/:team_id/signals/reports/:id/reviewers/me/': [204, null] },
        })
        await mountAt({ report: `r-${PAGE_SIZE - 2}`, at: PAGE_SIZE - 2 })
        inboxFiltersLogic.actions.setScope(INBOX_SCOPE_ENTIRE_PROJECT)
        await expectLogic(logic).toFinishAllListeners()
        requestedOffsets = []

        logic.actions.removeMeFromCurrent('hotkey')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.currentReport?.id).toBe(`r-${PAGE_SIZE - 1}`)
        expect(requestedOffsets).toEqual([String(PAGE_SIZE)])
        expect(logic.values.nextReport?.id).toBe(`r-${PAGE_SIZE}`)
    })

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
