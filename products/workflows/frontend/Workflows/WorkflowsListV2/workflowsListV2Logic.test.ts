import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { WorkflowStatsRowApi } from 'products/workflows/frontend/generated/api.schemas'

import type { WorkflowListRow } from './workflowListRows'
import {
    FIXTURE_METRICS,
    FIXTURE_USERS,
    FIXTURE_WORKFLOWS,
    buildWorkflowRow,
    paginated,
} from './workflowsListV2Fixtures'
import { workflowsListV2Logic } from './workflowsListV2Logic'

const shownIds = (logic: ReturnType<typeof workflowsListV2Logic.build>): string[] =>
    logic.values.filteredRows.map((row) => row.id)

describe('workflowsListV2Logic', () => {
    let logic: ReturnType<typeof workflowsListV2Logic.build>
    let workflowRequests: URLSearchParams[]
    let serverSearch: (search: string) => Promise<string[]>
    let metricsResponse: () => Promise<[number, WorkflowStatsRowApi[] | { detail: string }]>

    beforeEach(() => {
        workflowRequests = []
        serverSearch = async () => []
        metricsResponse = async () => [200, FIXTURE_METRICS]
        const byId = new Map(FIXTURE_WORKFLOWS.map((workflow) => [workflow.id, workflow]))
        // A workflow created during the load shifts the offsets, so page two repeats the last row of page one.
        const secondPage = [
            FIXTURE_WORKFLOWS[FIXTURE_WORKFLOWS.length - 1],
            buildWorkflowRow({ id: 'wf-page-two', name: 'Second page', updated_at: '2026-09-19T12:00:00Z' }),
        ]
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    workflowRequests.push(params)
                    const search = params.get('search')
                    if (search) {
                        try {
                            const ids = await serverSearch(search)
                            return [200, paginated(ids.map((id) => byId.get(id)!))]
                        } catch {
                            return [500, { detail: 'Server error' }]
                        }
                    }
                    if (params.get('offset') === '500') {
                        return [200, paginated(secondPage)]
                    }
                    return [
                        200,
                        paginated(
                            FIXTURE_WORKFLOWS,
                            'http://localhost/api/projects/997/hog_flows/summaries/?limit=500&offset=500'
                        ),
                    ]
                },
                '/api/projects/:team_id/hog_flows/metrics/global/': () => metricsResponse(),
            },
        })
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it('loads every page of workflows, newest first', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        expect(shownIds(logic)).toEqual(['wf-welcome', 'wf-page-two', 'wf-renewal', 'wf-sync', 'wf-old-promo'])
        expect(
            workflowRequests.map((params) => [params.get('limit'), params.get('offset'), params.get('type')])
        ).toEqual([
            ['500', null, 'messaging,automation,loop'],
            ['500', '500', 'messaging,automation,loop'],
        ])
    })

    it('stops following a next link that never ends and shows the load error', async () => {
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => {
                    requests++
                    return [
                        200,
                        paginated(
                            [buildWorkflowRow({ id: `wf-loop-${requests}` })],
                            'http://localhost/api/projects/997/hog_flows/summaries/?limit=500&offset=500'
                        ),
                    ]
                },
            },
        })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsFailure'])
        expect(logic.values.loadFailed).toBe(true)
        expect(requests).toBeLessThanOrEqual(100)
    })

    it('sends every request to the team id, which can differ from the project id', async () => {
        const TEAM_ID = 4242
        const paths: string[] = []
        const record =
            (body: unknown) =>
            ({ request }: { request: Request }): [number, unknown] => {
                paths.push(`${request.method} ${new URL(request.url).pathname}`)
                return [200, body]
            }
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': record(paginated(FIXTURE_WORKFLOWS)),
                '/api/projects/:team_id/hog_flows/metrics/global/': record(FIXTURE_METRICS),
                '/api/projects/:team_id/hog_flows/:id/': record({ ...FIXTURE_WORKFLOWS[0], actions: [], edges: [] }),
            },
            post: { '/api/projects/:team_id/hog_flows/': record({}) },
            patch: { '/api/projects/:team_id/hog_flows/:id/': record({}) },
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: TEAM_ID })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])

        const workflow = logic.values.rows.find((row) => row.id === 'wf-renewal')!
        await expectLogic(logic, () => logic.actions.toggleWorkflowStatus(workflow)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.duplicateWorkflow(workflow)).toDispatchActions([
            'loadWorkflowsSuccess',
        ])

        expect(paths.filter((path) => !path.includes(`/projects/${TEAM_ID}/`))).toEqual([])
        expect(new Set(paths)).toEqual(
            new Set([
                `GET /api/projects/${TEAM_ID}/hog_flows/summaries/`,
                `GET /api/projects/${TEAM_ID}/hog_flows/metrics/global/`,
                `PATCH /api/projects/${TEAM_ID}/hog_flows/wf-renewal/`,
                `GET /api/projects/${TEAM_ID}/hog_flows/wf-renewal/`,
                `POST /api/projects/${TEAM_ID}/hog_flows/`,
            ])
        )
    })

    it('shows a load error instead of an empty list', async () => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/summaries/': () => [500, { detail: 'Boom' }] } })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsFailure'])
        expect(logic.values.loadFailed).toBe(true)
        expect(logic.values.listLoaded).toBe(false)
    })

    it('shows the list before the metrics arrive, then fills in health', async () => {
        let answerMetrics: () => void = () => {}
        const metricsSent = new Promise<void>((markSent) => {
            metricsResponse = () =>
                new Promise((resolve) => {
                    answerMetrics = () => resolve([200, FIXTURE_METRICS])
                    markSent()
                })
        })
        router.actions.push(urls.workflows(), { q: 'health:idle' })
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetrics'])
        await metricsSent
        expect(logic.values.metricsLoading).toBe(true)
        expect(shownIds(logic)).toEqual(['wf-welcome', 'wf-page-two', 'wf-renewal', 'wf-sync', 'wf-old-promo'])

        answerMetrics()
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
        expect(shownIds(logic)).toEqual(['wf-page-two', 'wf-sync', 'wf-old-promo'])
        expect(logic.values.rows.find((row) => row.id === 'wf-renewal')).toMatchObject({
            health: 'failing',
            last7Days: { succeeded: 3, failed: 2 },
        })
        expect(logic.values.rows.find((row) => row.id === 'wf-old-promo')?.last7Days).toEqual({
            succeeded: 0,
            failed: 0,
        })
    })

    it('keeps the list and skips the error toast when the metrics fail', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        metricsResponse = async () => [500, { detail: 'Server error' }]
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])
        expect(logic.values).toMatchObject({ metrics: null, metricsLoading: false, loadFailed: false })
        expect(shownIds(logic)).toHaveLength(5)
        expect(toastError).not.toHaveBeenCalled()
        toastError.mockRestore()
    })

    it('moves old filter params into q and text once, replacing the history entry', async () => {
        router.actions.push(urls.workflows(), {
            status: 'active',
            type: 'loop',
            trigger_type: 'schedule',
            created_by: FIXTURE_USERS.lin.uuid,
            search: 'renew',
            page: '3',
            other: 'kept',
        })
        logic = workflowsListV2Logic()
        logic.mount()

        expect(router.values.searchParams).toEqual({
            q: `status:active type:loop trigger:schedule created-by:${FIXTURE_USERS.lin.uuid}`,
            text: 'renew',
            other: 'kept',
        })
        expect(router.values.lastMethod).toEqual('REPLACE')
        expect(logic.values.value).toEqual({
            filters: [
                { facet: 'status', value: 'active', negated: false },
                { facet: 'type', value: 'loop', negated: false },
                { facet: 'trigger', value: 'schedule', negated: false },
                { facet: 'created-by', value: FIXTURE_USERS.lin.uuid, negated: false },
            ],
            text: 'renew',
        })
    })

    it('keeps a later page param, because only the first URL is a bookmarked old link', async () => {
        router.actions.push(urls.workflows(), { q: 'status:active' })
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        router.actions.push(router.values.location.pathname, { ...router.values.searchParams, page: 2 })
        expect(router.values.searchParams).toEqual({ q: 'status:active', page: 2 })
    })

    it.each(['text', 'search'])('keeps number-like free text from the %s param as written', async (param) => {
        // A pasted link reaches the router as written; `router.actions.push` would already parse `007` to 7.
        router.actions.locationChanged({
            method: 'PUSH',
            pathname: urls.workflows(),
            search: `?${param}=007`,
            searchParams: { [param]: 7 },
            hash: '',
            hashParams: {},
            url: `${urls.workflows()}?${param}=007`,
        })
        logic = workflowsListV2Logic()
        logic.mount()

        expect(logic.values.value.text).toEqual('007')
        logic.actions.setValue({ filters: [], text: '0070' })
        expect(logic.values.value.text).toEqual('0070')
        expect(router.values.location.search).toEqual('?text=0070')
    })

    it('drops old params with values it does not know', () => {
        router.actions.push(urls.workflows(), { status: 'all', trigger_type: 'bogus', created_by: 'not-a-uuid' })
        logic = workflowsListV2Logic()
        logic.mount()

        expect(router.values.searchParams).toEqual({})
    })

    it('ORs the server search into the text match and ignores a stale answer', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        let answerSlowSearch: (ids: string[]) => void = () => {}
        let markSlowSearchSent: () => void = () => {}
        const slowSearchSent = new Promise<void>((resolve) => {
            markSlowSearchSent = resolve
        })
        serverSearch = (search) => {
            if (search === 'spring') {
                markSlowSearchSent()
                return new Promise((resolve) => {
                    answerSlowSearch = resolve
                })
            }
            return Promise.resolve(search === 'renewal' ? ['wf-sync'] : [])
        }

        logic.actions.setValue({ filters: [], text: 'spring' })
        await slowSearchSent
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'renewal' })).toDispatchActions([
            'searchWorkflowsSuccess',
        ])
        // Only the client match on the name, plus the workflow the server found in an email body.
        expect(shownIds(logic)).toEqual(['wf-renewal', 'wf-sync'])

        answerSlowSearch(['wf-old-promo'])
        await expectLogic(logic).toFinishAllListeners()
        expect(shownIds(logic)).toEqual(['wf-renewal', 'wf-sync'])
        expect(workflowRequests.map((params) => params.get('search')).filter(Boolean)).toEqual(['spring', 'renewal'])

        // Back to the earlier text while a newer search is still out: the late answer must not replace it.
        let answerDetour: (ids: string[]) => void = () => {}
        let markDetourSent: () => void = () => {}
        const detourSent = new Promise<void>((resolve) => {
            markDetourSent = resolve
        })
        serverSearch = (search) => {
            if (search === 'renewalx') {
                markDetourSent()
                return new Promise((resolve) => {
                    answerDetour = resolve
                })
            }
            return Promise.resolve(search === 'renewal' ? ['wf-sync'] : [])
        }
        logic.actions.setValue({ filters: [], text: 'renewalx' })
        await detourSent
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'renewal' })).toDispatchActions([
            'searchWorkflowsSuccess',
        ])
        answerDetour([])
        await expectLogic(logic).toFinishAllListeners()
        expect(shownIds(logic)).toEqual(['wf-renewal', 'wf-sync'])
    })

    it('does not ask the server for text under 3 characters', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 're' })).toFinishAllListeners()
        expect(workflowRequests.map((params) => params.get('search')).filter(Boolean)).toEqual([])
        expect(logic.values.serverSearchStatus).toEqual('off')
    })

    it('holds the no-match verdict until the server search answers, and reports a failed search without a toast', async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        let answerSearch: (ids: string[]) => void = () => {}
        const searchSent = new Promise<void>((markSent) => {
            serverSearch = () =>
                new Promise((resolve) => {
                    answerSearch = resolve
                    markSent()
                })
        })
        logic.actions.setValue({ filters: [], text: 'invoice' })
        expect(logic.values.serverSearchStatus).toEqual('pending')
        expect(shownIds(logic)).toEqual([])

        await searchSent
        answerSearch(['wf-sync'])
        await expectLogic(logic).toDispatchActions(['searchWorkflowsSuccess'])
        expect(logic.values.serverSearchStatus).toEqual('done')
        expect(shownIds(logic)).toEqual(['wf-sync'])

        serverSearch = () => Promise.reject(new Error('down'))
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'renewal' })).toDispatchActions([
            'searchWorkflowsSuccess',
        ])
        expect(logic.values.serverSearchStatus).toEqual('failed')
        expect(shownIds(logic)).toEqual(['wf-renewal'])
        expect(toastError).not.toHaveBeenCalled()
        toastError.mockRestore()
    })

    it.each([
        ['succeeds', 200, 1],
        ['fails', 500, 0],
    ])('sends one duplicate at a time and clears the pending state when the copy %s', async (_, status, copies) => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])

        let answerRetrieve: () => void = () => {}
        let posts = 0
        const retrieveSent = new Promise<void>((markSent) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_flows/summaries/': () => [200, paginated(FIXTURE_WORKFLOWS)],
                    '/api/projects/:team_id/hog_flows/:id/': () =>
                        new Promise((resolve) => {
                            answerRetrieve = () =>
                                resolve(
                                    status === 200
                                        ? [200, { ...FIXTURE_WORKFLOWS[1], actions: [], edges: [] }]
                                        : [500, {}]
                                )
                            markSent()
                        }),
                },
                post: {
                    '/api/projects/:team_id/hog_flows/': () => {
                        posts++
                        return [200, { id: `wf-copy-${posts}` }]
                    },
                },
            })
        })
        const row = logic.values.rows.find((r) => r.id === 'wf-renewal')!

        logic.actions.duplicateWorkflow(row)
        logic.actions.duplicateWorkflow(row)
        expect(logic.values.pendingRowActions).toEqual({ 'wf-renewal': 'duplicate' })

        await retrieveSent
        answerRetrieve()
        await expectLogic(logic).toFinishAllListeners()
        expect(posts).toEqual(copies)
        expect(logic.values.pendingRowActions).toEqual({})
    })

    it.each([
        ['enable', 'wf-sync', 'active', (row: WorkflowListRow) => logic.actions.toggleWorkflowStatus(row)],
        ['restore', 'wf-old-promo', 'draft', (row: WorkflowListRow) => logic.actions.restoreWorkflow(row)],
    ])('%s takes the status and updated_at from the server answer', async (_, id, status, run) => {
        useMocks({
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': () => [200, { status, updated_at: '2026-09-27T12:00:00Z' }],
            },
        })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        await expectLogic(logic, () => run(logic.values.rows.find((row) => row.id === id)!)).toFinishAllListeners()
        expect(logic.values.rows[0].workflow).toMatchObject({ id, status, updated_at: '2026-09-27T12:00:00Z' })
    })
})
