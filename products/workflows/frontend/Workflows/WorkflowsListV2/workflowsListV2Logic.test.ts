import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

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

    it.each(['messaging', 'automation'])('opens templates for the active %s facet', (type) => {
        logic = workflowsListV2Logic()
        logic.mount()
        logic.actions.setValue({ filters: [{ facet: 'kind', value: type, negated: false }], text: '' })
        expect(logic.values.templateTypeFilter).toBe(type)
        logic.actions.setValue({
            filters: [
                { facet: 'kind', value: 'messaging', negated: false },
                { facet: 'kind', value: 'automation', negated: false },
            ],
            text: '',
        })
        expect(logic.values.templateTypeFilter).toBe('all')
    })

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

    it.each([
        ['createdBy:me', 'createdBy:me'],
        ['CREATEDBY:me', 'createdBy:me'],
        ['created-by:me', 'createdBy:me'],
        ['by:me', 'createdBy:me'],
        ['Author:me', 'createdBy:me'],
        ['user:me', 'createdBy:me'],
        ['type:messaging createdBy:me', 'createdBy:me'],
    ])('reads %s as the signed-in user and links to %s', async (q, canonical) => {
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid: FIXTURE_USERS.lin.uuid, first_name: 'Lin' })
        router.actions.push(urls.workflows(), { q })
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        expect(shownIds(logic)).toEqual(['wf-sync'])
        expect(router.values.searchParams).toEqual({ q: canonical })
        expect(logic.values.facets.find((facet) => facet.key === 'createdBy')?.formatValue?.('me')).toEqual('Lin')
    })

    it('follows next links for as many pages as the project has', async () => {
        const pageCount = 45
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => {
                    const page = Number(new URL(request.url).searchParams.get('offset') ?? 0) / 500
                    const next =
                        page + 1 < pageCount
                            ? `http://localhost/api/projects/997/hog_flows/summaries/?limit=500&offset=${(page + 1) * 500}`
                            : null
                    return [200, paginated([buildWorkflowRow({ id: `wf-page-${page}` })], next)]
                },
            },
        })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        expect(logic.values.rows).toHaveLength(pageCount)
    })

    it.each([
        ['an owner as the list shows it', 'owner:@maya', ['wf-welcome']],
        ['a health label', 'health:"No runs"', ['wf-page-two', 'wf-sync', 'wf-old-promo']],
        ['a creator name', 'createdBy:Ada', ['wf-welcome', 'wf-page-two', 'wf-renewal', 'wf-old-promo']],
    ])('matches a link with %s', async (_, q, ids) => {
        router.actions.push(urls.workflows(), { q })
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])
        expect(shownIds(logic)).toEqual(ids)
    })

    it('leaves a creator name that two people share unresolved', async () => {
        const otherAda = { ...FIXTURE_USERS.ada, id: 3, uuid: '0190a1b2-0000-7000-8000-00000000a003' }
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': () => [
                    200,
                    paginated([
                        buildWorkflowRow({ id: 'wf-first-ada' }),
                        buildWorkflowRow({ id: 'wf-second-ada', created_by: otherAda }),
                    ]),
                ],
            },
        })
        router.actions.push(urls.workflows(), { q: 'createdBy:Ada' })
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])
        expect(shownIds(logic)).toEqual([])
    })

    it('stops at a next link that does not move forward and shows the load error', async () => {
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
        expect(logic.values.loadErrorDetail).toEqual(
            'Loading stopped after 2 workflows because the server kept sending the same page. Try again.'
        )
        expect(requests).toEqual(2)
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

    it.each([
        ['a server error', 500, { detail: 'Boom' }, 'Boom'],
        [
            'missing access',
            403,
            { type: 'authentication_error', code: 'permission_denied', detail: 'You do not have permission.' },
            'You need at least viewer access to workflows in this project. Ask a project admin for it.',
        ],
    ])('shows a load error that says why for %s', async (_, status, body, detail) => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/summaries/': () => [status, body] } })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsFailure'])
        expect(logic.values.loadFailed).toBe(true)
        expect(logic.values.listLoaded).toBe(false)
        expect(logic.values.loadErrorDetail).toEqual(detail)
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
        expect(shownIds(logic)).toEqual([])

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
            q: `status:active kind:loop trigger:schedule createdBy:${FIXTURE_USERS.lin.uuid}`,
            text: 'renew',
            other: 'kept',
        })
        expect(router.values.lastMethod).toEqual('REPLACE')
        expect(logic.values.value).toEqual({
            filters: [
                { facet: 'status', value: 'active', negated: false },
                { facet: 'kind', value: 'loop', negated: false },
                { facet: 'trigger', value: 'schedule', negated: false },
                { facet: 'createdBy', value: FIXTURE_USERS.lin.uuid, negated: false },
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

    it('shows a copy that only the server search matches', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        serverSearch = async () => ['wf-sync']
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'ledger' })).toDispatchActions([
            'searchWorkflowsSuccess',
        ])
        expect(shownIds(logic)).toEqual(['wf-sync'])

        const copy = buildWorkflowRow({ id: 'wf-sync-copy', name: 'Sync accounts to CRM (copy)' })
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new URL(request.url).searchParams.get('search')
                        ? [200, paginated([FIXTURE_WORKFLOWS[2], copy])]
                        : [200, paginated([...FIXTURE_WORKFLOWS, copy])],
                '/api/projects/:team_id/hog_flows/:id/': () => [
                    200,
                    { ...FIXTURE_WORKFLOWS[2], actions: [], edges: [] },
                ],
            },
            post: { '/api/projects/:team_id/hog_flows/': () => [200, { id: copy.id }] },
        })

        logic.actions.duplicateWorkflow(logic.values.rows.find((row) => row.id === 'wf-sync')!)
        await expectLogic(logic).toFinishAllListeners()
        expect(shownIds(logic)).toEqual(['wf-sync', 'wf-sync-copy'])
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
