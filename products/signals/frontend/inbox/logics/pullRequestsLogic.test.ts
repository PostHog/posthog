import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import { expectLogic } from 'kea-test-utils'

import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { PRBrowserItemApi } from 'products/signals/frontend/generated/api.schemas'

import { latestPrMonitoringGuidanceQuestion, selectVisibleReportActivity } from '../components/detail/artefactTypes'
import { inboxSceneLogic } from '../inboxSceneLogic'
import type { SignalReportArtefact } from '../types'
import { prMonitoringWindowExpiredReason } from '../utils/reportPullRequests'
import { monitoringTabLogic } from './monitoringTabLogic'
import { pullRequestsLogic } from './pullRequestsLogic'

const PULL_REQUESTS_URL = '/api/projects/:team_id/signals/pull_requests/'
const MONITOR_PR_URL = '/api/projects/:team_id/signals/monitor_pr/'
const REPORTS_URL = '/api/projects/:team_id/signals/reports/'

const makePR = (number: number, overrides: Partial<PRBrowserItemApi> = {}): PRBrowserItemApi => ({
    url: `https://github.com/example/widget/pull/${number}`,
    repository: 'example/widget',
    number,
    title: `Change ${number}`,
    state: 'open',
    draft: false,
    author: 'example-author',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    report: null,
    ...overrides,
})

describe('pullRequestsLogic', () => {
    let logic: ReturnType<typeof pullRequestsLogic.build>
    let listRequests: number
    let monitorPayloads: Record<string, unknown>[]
    let reportLoads: number

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        listRequests = 0
        monitorPayloads = []
        reportLoads = 0
        useMocks({
            get: {
                [PULL_REQUESTS_URL]: () => {
                    listRequests += 1
                    return [
                        200,
                        {
                            results: [
                                makePR(1, { state: 'open' }),
                                makePR(2, { state: 'merged' }),
                                makePR(3, { state: 'merged', report: { id: 'rep-3', status: 'failed' } }),
                                makePR(4, { state: 'merged', report: { id: 'rep-4', status: 'monitoring' } }),
                            ],
                            github_login: 'example-author',
                            has_integration: true,
                        },
                    ]
                },
                [REPORTS_URL]: () => {
                    reportLoads += 1
                    return [200, { results: [], count: 0, next: null, previous: null }]
                },
            },
            post: {
                [MONITOR_PR_URL]: async ({ request }) => {
                    const body = (await request.json()) as { pr_url: string }
                    monitorPayloads.push(body)
                    const suffix = body.pr_url.split('/').pop()
                    return [
                        202,
                        {
                            report_id: `rep-${suffix}`,
                            report_url: `http://localhost:8000/project/997/inbox/reports/rep-${suffix}`,
                            status: 'in_progress',
                            idempotent_replay: false,
                        },
                    ]
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('filters loaded PRs client-side by monitoring and GitHub state without refetching', async () => {
        logic = pullRequestsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])

        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([1, 2, 3, 4])

        logic.actions.setFilter('unmonitored')
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([1, 2])

        logic.actions.setFilter('monitored')
        logic.actions.setStateFilter('merged')
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([3, 4])

        logic.actions.setFilter('all')
        logic.actions.setStateFilter('open')
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([1])
        expect(listRequests).toBe(1)
    })

    it('preserves concurrent monitoring submissions across multiple PRs and refreshes the monitoring list', async () => {
        const monitoringLogic = monitoringTabLogic()
        monitoringLogic.mount()
        await expectLogic(monitoringLogic).toFinishAllListeners()
        const loadsBefore = reportLoads

        logic = pullRequestsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])

        const url1 = 'https://github.com/example/widget/pull/1'
        const url2 = 'https://github.com/example/widget/pull/2'
        logic.actions.monitorPR(url1)
        logic.actions.monitorPR(url2)
        expect(logic.values.monitoringUrls).toEqual({ [url1]: true, [url2]: true })

        await expectLogic(logic).toFinishAllListeners()

        expect(monitorPayloads).toEqual([{ pr_url: url1 }, { pr_url: url2 }])
        expect(logic.values.monitoringUrls).toEqual({})
        expect(logic.values.page?.results[0].report).toEqual({ id: 'rep-1', status: 'in_progress' })
        expect(logic.values.page?.results[1].report).toEqual({ id: 'rep-2', status: 'in_progress' })
        expect(reportLoads).toBeGreaterThan(loadsBefore)
        monitoringLogic.unmount()
    })

    it('keeps a monitored PR visible in the timeline when started from a child environment', async () => {
        const reportId = 'rep-5'
        const requestedPaths: string[] = []
        let monitoringStarted = false
        useMocks({
            get: {
                [PULL_REQUESTS_URL]: ({ request }) => {
                    requestedPaths.push(new URL(request.url).pathname)
                    return [
                        200,
                        {
                            results: [makePR(5)],
                            github_login: 'example-author',
                            has_integration: true,
                        },
                    ]
                },
                [REPORTS_URL]: ({ request }) => {
                    requestedPaths.push(new URL(request.url).pathname)
                    return [
                        200,
                        {
                            count: monitoringStarted ? 1 : 0,
                            next: null,
                            previous: null,
                            results: monitoringStarted
                                ? [{ id: reportId, metrics: [], monitoring_summary: null, monitoring_outcome: null }]
                                : [],
                        },
                    ]
                },
            },
            post: {
                [MONITOR_PR_URL]: ({ request }) => {
                    requestedPaths.push(new URL(request.url).pathname)
                    monitoringStarted = true
                    return [
                        202,
                        {
                            report_id: reportId,
                            report_url: `http://localhost:8000/project/99/inbox/reports/${reportId}`,
                            status: 'in_progress',
                            idempotent_replay: false,
                        },
                    ]
                },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 4242, project_id: 99 })
        projectLogic.actions.loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, id: 99 })

        const monitoringLogic = monitoringTabLogic()
        monitoringLogic.mount()
        await expectLogic(monitoringLogic).toFinishAllListeners()
        logic = pullRequestsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])

        logic.actions.monitorPR('https://github.com/example/widget/pull/5')
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(monitoringLogic).toFinishAllListeners()

        expect(monitoringLogic.values.reports?.map((report) => report.id)).toEqual([reportId])
        expect(requestedPaths).toEqual([
            '/api/projects/99/signals/reports/',
            '/api/projects/99/signals/pull_requests/',
            '/api/projects/99/signals/monitor_pr/',
            '/api/projects/99/signals/reports/',
        ])
        monitoringLogic.unmount()
    })

    it('skips loading PRs while collapsed, loads when expanded, and retries failed research with an optional note', async () => {
        localStorage.setItem('products.signals.inbox.pullRequestsLogic.panelOpen', JSON.stringify(false))

        logic = pullRequestsLogic()
        logic.mount()
        expect(logic.values.panelOpen).toBe(false)
        expect(listRequests).toBe(0)

        logic.actions.setPanelOpen(true)
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])
        expect(listRequests).toBe(1)

        const prUrl = 'https://github.com/example/widget/pull/3'
        useMocks({
            post: {
                [MONITOR_PR_URL]: () => [503, { detail: 'GitHub temporarily unavailable' }],
            },
        })
        logic.actions.openComposer(prUrl)
        logic.actions.setDraftNote(prUrl, '  Watch payment retries  ')
        logic.actions.monitorPR(prUrl)
        logic.actions.monitorPR(prUrl)
        await expectLogic(logic).toDispatchActions(['monitorPRDone'])
        expect(logic.values.composingUrl).toBe(prUrl)
        expect(logic.values.draftNotes[prUrl]).toBe('  Watch payment retries  ')

        useMocks({
            post: {
                [MONITOR_PR_URL]: async ({ request }) => {
                    const body = (await request.json()) as Record<string, unknown>
                    monitorPayloads.push(body)
                    return [
                        202,
                        {
                            report_id: 'rep-3',
                            report_url: 'http://localhost:8000/project/997/inbox/reports/rep-3',
                            status: 'in_progress',
                            idempotent_replay: false,
                        },
                    ]
                },
            },
        })
        logic.actions.monitorPR(prUrl)
        await expectLogic(logic).toDispatchActions(['monitorPRDone'])
        expect(monitorPayloads).toEqual([{ pr_url: prUrl, note: 'Watch payment retries' }])
        expect(logic.values.composingUrl).toBeNull()
        expect(logic.values.draftNotes[prUrl]).toBeUndefined()
        expect(logic.values.page?.results[2].report?.status).toBe('in_progress')
    })

    it('discards failed requests from a previous mount while surfacing active failures', async () => {
        let markFirstLoadStarted!: () => void
        const firstLoadStarted = new Promise<void>((resolve) => {
            markFirstLoadStarted = resolve
        })
        let rejectFirstLoad!: (error: Error) => void
        let callCount = 0
        useMocks({
            get: {
                [PULL_REQUESTS_URL]: () => {
                    callCount += 1
                    if (callCount === 1) {
                        markFirstLoadStarted()
                        return new Promise((_resolve, reject) => {
                            rejectFirstLoad = reject
                        })
                    }
                    if (callCount === 2) {
                        return [
                            200,
                            {
                                results: [makePR(10)],
                                github_login: 'example-author',
                                has_integration: true,
                            },
                        ]
                    }
                    return [503, { detail: 'GitHub unavailable' }]
                },
            },
        })

        logic = pullRequestsLogic()
        logic.mount()
        await firstLoadStarted
        logic.unmount()

        logic = pullRequestsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsSuccess'])
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([10])
        expect(logic.values.listError).toBe(false)

        rejectFirstLoad(new Error('stale mount failed'))
        await Promise.resolve()
        await Promise.resolve()
        expect(logic.values.listError).toBe(false)
        expect(logic.values.filteredPRs.map((pr) => pr.number)).toEqual([10])

        logic.actions.loadPullRequests()
        await expectLogic(logic).toDispatchActions(['loadPullRequestsFailure'])
        expect(logic.values.listError).toBe(true)
    })

    it('syncs the open report on guidance submission and hides internal check_authoring activity rows', async () => {
        localStorage.setItem('products.signals.inbox.pullRequestsLogic.panelOpen', JSON.stringify(false))
        let reportStatus = 'pending_input'
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/:id/': ({ params }) => [
                    200,
                    {
                        id: String(params.id),
                        title: 'Monitor PR',
                        summary: 'Post-merge impact check.',
                        status: reportStatus,
                        signal_count: 0,
                        total_weight: 0,
                        created_at: '2026-01-01T00:00:00Z',
                        updated_at: '2026-01-01T00:00:00Z',
                    },
                ],
                '/api/projects/:team_id/signals/config/': () => [200, { enabled: true }],
                '/api/projects/:team_id/signals/scouts/': () => [200, []],
            },
        })

        const scene = inboxSceneLogic()
        scene.mount()
        scene.actions.setSelectedReportId('rep-3')
        await expectLogic(scene).toDispatchActions(['loadSelectedReportSuccess'])
        expect(scene.values.selectedReport?.status).toBe('pending_input')

        logic = pullRequestsLogic()
        logic.mount()
        const prUrl = 'https://github.com/example/widget/pull/3'
        reportStatus = 'in_progress'
        logic.actions.setDraftNote(prUrl, 'Monitor order_submitted')
        await expectLogic(logic, () => {
            logic.actions.monitorPR(prUrl)
        }).toDispatchActions(['monitorPRDone'])
        await expectLogic(scene).toFinishAllListeners()
        expect(scene.values.selectedReport?.status).toBe('in_progress')

        scene.actions.setSelectedReportId('rep-teammate')
        await expectLogic(scene).toDispatchActions(['loadSelectedReportSuccess'])
        await expectLogic(logic, () => {
            logic.actions.monitorPR(prUrl, 'Monitor order_submitted')
        }).toDispatchActions(['monitorPRDone'])
        expect(scene.values.selectedReportId).toBe('rep-3')

        let finishPendingMonitor!: () => void
        useMocks({
            post: {
                [MONITOR_PR_URL]: () =>
                    new Promise((resolve) => {
                        finishPendingMonitor = () =>
                            resolve([
                                202,
                                {
                                    report_id: 'rep-3',
                                    report_url: 'http://localhost:8000/project/997/inbox/reports/rep-3',
                                    status: 'in_progress',
                                    idempotent_replay: false,
                                },
                            ])
                    }),
            },
        })
        logic.actions.monitorPR(prUrl, 'Monitor order_submitted')
        scene.actions.setSelectedReportId('rep-other')
        await expectLogic(scene).toDispatchActions(['loadSelectedReportSuccess'])
        finishPendingMonitor()
        await expectLogic(logic).toDispatchActions(['monitorPRDone'])
        expect(scene.values.selectedReportId).toBe('rep-other')
        scene.unmount()

        const artefacts = [
            { id: '1', type: 'check_authoring', content: { status: 'failed' }, created_at: '2026-01-01T00:00:00Z' },
            {
                id: '2',
                type: 'note',
                actor_kind: 'system',
                content: { note: 'Monitor `order_submitted`?', author: 'PR monitoring' },
                created_at: '2026-01-01T00:00:01Z',
            },
            {
                id: '3',
                type: 'note',
                actor_kind: 'system',
                content: { note: "You don't have access to this assessment's evidence.", author: 'PR monitoring' },
                created_at: '2026-01-01T00:00:02Z',
            },
        ] as unknown as SignalReportArtefact[]
        expect(selectVisibleReportActivity(artefacts).map((item) => item.id)).toEqual(['2', '3'])
        expect(latestPrMonitoringGuidanceQuestion(artefacts.slice(0, 2))).toBe('Monitor `order_submitted`?')
        expect(latestPrMonitoringGuidanceQuestion(artefacts)).toBeNull()

        const nowMs = Date.parse('2026-06-01T00:00:00Z')
        expect(
            prMonitoringWindowExpiredReason(
                {
                    pull_requests: [
                        {
                            id: 'pr-1',
                            url: prUrl,
                            state: 'merged',
                            merged: true,
                            review_decision: null,
                            merged_at: '2026-02-01T00:00:00Z',
                            attached_by: null,
                            claim_id: null,
                            attached_at: '2026-02-01T00:00:00Z',
                        },
                    ],
                },
                prUrl,
                nowMs
            )
        ).toBe('Pull requests merged more than 90 days ago are outside the monitoring window')
    })
})
