import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { act, render, screen } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { WorkflowStatsRowApi } from 'products/workflows/frontend/generated/api.schemas'

import { customerioImportLogic } from '../import/customerioImportLogic'
import type { WorkflowListRow } from './workflowListRows'
import {
    FIXTURE_METRICS,
    FIXTURE_USERS,
    FIXTURE_WORKFLOWS,
    buildWorkflowRow,
    paginated,
} from './workflowsListV2Fixtures'
import { SUMMARY_REQUEST_TIMEOUT_MS, workflowsListV2Logic } from './workflowsListV2Logic'

const shownIds = (logic: ReturnType<typeof workflowsListV2Logic.build>): string[] =>
    logic.values.filteredRows.map((row) => row.id)

describe('workflowsListV2Logic', () => {
    let logic: ReturnType<typeof workflowsListV2Logic.build>
    let workflowRequests: URLSearchParams[]
    let searchSignals: AbortSignal[]
    let serverSearch: (search: string) => Promise<string[]>
    let metricsResponse: () => Promise<[number, WorkflowStatsRowApi[] | { detail: string }]>

    beforeEach(() => {
        localStorage.clear()
        workflowRequests = []
        searchSignals = []
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
                        searchSignals.push(request.signal)
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
        lemonToast.dismiss()
        render(createElement(jest.requireActual('react-toastify').ToastContainer))
    })

    afterEach(() => {
        if (logic?.isMounted()) {
            logic.unmount()
        }
    })

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

    it.each(['in', 'path', 'folder', 'Folder'])('restores a project folder from %s: in the URL', async (key) => {
        logic = workflowsListV2Logic()
        logic.mount()
        router.actions.push(urls.workflows(), { q: `${key}:Campaigns status:active` })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.value.filters).toEqual([
            { facet: 'in', value: 'Campaigns', negated: false },
            { facet: 'status', value: 'active', negated: false },
        ])
        expect(router.values.searchParams.q).toBe('in:Campaigns status:active')
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

    const LIN_SYNC: [string, string[]] = ['Lin', ['wf-sync']]
    const ADA_OWNS: [string, string[]] = ['Ada', ['wf-page-two', 'wf-renewal', 'wf-old-promo']]

    it.each([
        ['createdBy:me', 'createdBy:me', ...LIN_SYNC],
        ['CREATEDBY:ME', 'createdBy:me', ...LIN_SYNC],
        ['created-by:me', 'createdBy:me', ...LIN_SYNC],
        ['by:me', 'createdBy:me', ...LIN_SYNC],
        ['Author:me', 'createdBy:me', ...LIN_SYNC],
        ['user:me', 'createdBy:me', ...LIN_SYNC],
        ['type:messaging createdBy:me', 'createdBy:me', ...LIN_SYNC],
        ['owner:me', 'owner:me', ...ADA_OWNS],
        ['owner:@Me', 'owner:me', ...ADA_OWNS],
    ])('reads %s as the signed-in user and links to %s', async (q, canonical, viewer, ids) => {
        const { uuid, email, first_name } =
            viewer === 'Ada' ? FIXTURE_USERS.ada : { ...FIXTURE_USERS.lin, first_name: 'Lin' }
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid, email, first_name: first_name ?? '' })
        router.actions.push(urls.workflows(), { q })
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        expect(shownIds(logic)).toEqual(ids)
        expect(router.values.searchParams).toEqual({ q: canonical })
        const facet = logic.values.facets.find((facet) => facet.key === canonical.split(':')[0])
        expect(facet?.formatValue?.('me')).toEqual('Me')
        expect(facet?.pinnedValues).toEqual(['me'])
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

    it('leaves a creator name that two people share unresolved, and tells them apart by email', async () => {
        const otherAda = {
            ...FIXTURE_USERS.ada,
            id: 3,
            uuid: '0190a1b2-0000-7000-8000-00000000a003',
            email: 'ada.two@example.com',
        }
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
        const createdBy = logic.values.facets.find((facet) => facet.key === 'createdBy')!
        expect([FIXTURE_USERS.ada.uuid, otherAda.uuid].map((uuid) => createdBy.formatValue?.(uuid))).toEqual([
            'Ada (ada@example.com)',
            'Ada (ada.two@example.com)',
        ])
        expect(createdBy.resolveValue?.('ada.two@example.com')).toEqual(otherAda.uuid)
    })

    it.each([
        ['a link without them', {}],
        ['a reload of the same link', { q: 'status:draft', text: 'invoice' }],
    ])('brings the filters back and searches the server again when the list opens from %s', async (_, params) => {
        serverSearch = async () => ['wf-sync']
        router.actions.push(urls.workflows(), { q: 'status:draft', text: 'invoice' })
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'searchWorkflowsSuccess'])
        logic.unmount()

        router.actions.push(urls.workflows(), params)
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'searchWorkflowsSuccess'])
        expect(router.values.searchParams).toEqual({ q: 'status:draft', text: 'invoice' })
        expect(logic.values.serverSearchStatus).toEqual('done')
        expect(shownIds(logic)).toEqual(['wf-sync'])
    })

    it('shows each page as it arrives, keeps the rows when a later page fails, and loads the rest on retry', async () => {
        type HeldPage = { offset: string; answer: (status: number, body: unknown) => void }
        const held: HeldPage[] = []
        let markHeld: () => void = () => {}
        const nextHeld = async (): Promise<HeldPage> => {
            if (!held.length) {
                await new Promise<void>((resolve) => (markHeld = resolve))
            }
            return held.shift()!
        }
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) =>
                    new Promise((resolve) => {
                        held.push({
                            offset: new URL(request.url).searchParams.get('offset') ?? '0',
                            answer: (status, body) => resolve([status, body]),
                        })
                        markHeld()
                    }),
            },
        })
        const pageOf = (offset: number): unknown =>
            paginated(
                [buildWorkflowRow({ id: `wf-at-${offset}` })],
                offset < 1000 ? `http://localhost/api/projects/997/hog_flows/summaries/?offset=${offset + 500}` : null
            )
        const shownSorted = (): string[] => logic.values.rows.map((row) => row.id).sort()
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        ;(await nextHeld()).answer(200, pageOf(0))
        const second = await nextHeld()
        expect(shownSorted()).toEqual(['wf-at-0'])
        expect(logic.values).toMatchObject({ listComplete: false, loadingMoreWorkflows: true })
        second.answer(200, pageOf(500))
        const third = await nextHeld()
        expect(third.offset).toEqual('1000')
        third.answer(500, { detail: 'Boom' })
        await act(async () => {
            await expectLogic(logic).toDispatchActions(['loadWorkflowsFailure'])
        })
        expect(screen.queryByText(/Showing the list from before/)).toBeNull()
        expect(shownSorted()).toEqual(['wf-at-0', 'wf-at-500'])
        expect(logic.values).toMatchObject({
            listComplete: false,
            loadingMoreWorkflows: false,
            loadFailed: true,
            loadErrorDetail: 'Boom',
        })

        logic.actions.loadWorkflows()
        ;(await nextHeld()).answer(200, pageOf(0))
        const retriedSecond = await nextHeld()
        expect(shownSorted()).toEqual(['wf-at-0', 'wf-at-500'])
        expect(logic.values).toMatchObject({ loadFailed: false, loadingMoreWorkflows: true })
        retriedSecond.answer(200, pageOf(500))
        ;(await nextHeld()).answer(200, pageOf(1000))
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        expect(shownSorted()).toEqual(['wf-at-0', 'wf-at-1000', 'wf-at-500'])
        expect(logic.values).toMatchObject({ listComplete: true, loadingMoreWorkflows: false })
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

    const stalledRequests = (): {
        signals: AbortSignal[]
        requested: Promise<void>
        stall: ({ request }: { request: Request }) => Promise<never>
    } => {
        const signals: AbortSignal[] = []
        let markRequested: () => void = () => {}
        const requested = new Promise<void>((resolve) => (markRequested = resolve))
        const stall = ({ request }: { request: Request }): Promise<never> => {
            signals.push(request.signal)
            markRequested()
            return new Promise(() => {})
        }
        return { signals, requested, stall }
    }

    it('fails a stalled summary request at its deadline and aborts it', async () => {
        const { signals, stall } = stalledRequests()
        useMocks({ get: { '/api/projects/:team_id/hog_flows/summaries/': stall } })
        router.actions.push(urls.workflows())
        jest.useFakeTimers()
        try {
            logic = workflowsListV2Logic()
            logic.mount()
            await jest.advanceTimersByTimeAsync(SUMMARY_REQUEST_TIMEOUT_MS)
            expect(logic.values).toMatchObject({
                workflowsLoading: false,
                loadFailed: true,
                loadErrorDetail: 'Workflows took too long to load. Check your connection and try again.',
            })
            expect(signals.map((signal) => signal.aborted)).toEqual([true])
        } finally {
            jest.useRealTimers()
        }
    })

    it('fails a stalled metrics request at its deadline and aborts it, and a retry loads them', async () => {
        const { signals, requested, stall } = stalledRequests()
        useMocks({ get: { '/api/projects/:team_id/hog_flows/metrics/global/': stall } })
        router.actions.push(urls.workflows(), { q: 'health:failing' })
        jest.useFakeTimers()
        try {
            logic = workflowsListV2Logic()
            logic.mount()
            await requested
            expect(logic.values.metricsStatus).toEqual('loading')
            await jest.advanceTimersByTimeAsync(SUMMARY_REQUEST_TIMEOUT_MS)
            expect(logic.values).toMatchObject({ metricsLoading: false, metricsStatus: 'failed' })
            expect(signals.map((signal) => signal.aborted)).toEqual([true])
        } finally {
            jest.useRealTimers()
        }

        useMocks({ get: { '/api/projects/:team_id/hog_flows/metrics/global/': () => [200, FIXTURE_METRICS] } })
        await expectLogic(logic, () => logic.actions.loadMetrics()).toFinishAllListeners()
        expect(logic.values.metricsStatus).toEqual('loaded')
        expect(shownIds(logic)).toEqual(['wf-renewal'])
    })

    it.each([
        ['summary', '/api/projects/:team_id/hog_flows/summaries/'],
        ['metrics', '/api/projects/:team_id/hog_flows/metrics/global/'],
    ])('aborts a running %s request when the list closes', async (_, path) => {
        const { signals, requested, stall } = stalledRequests()
        useMocks({ get: { [path]: stall } })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await requested
        logic.unmount()
        expect(signals.map((signal) => signal.aborted)).toEqual([true])
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

        let answerRefreshedMetrics: () => void = () => {}
        const refreshedMetricsSent = new Promise<void>((markSent) => {
            metricsResponse = () =>
                new Promise((resolve) => {
                    answerRefreshedMetrics = () =>
                        resolve([200, [{ workflow_id: 'wf-renewal', succeeded: 9, failed: 0 }]])
                    markSent()
                })
        })
        await expectLogic(logic, () => logic.actions.refreshWorkflows()).toDispatchActions(['loadWorkflowsSuccess'])
        expect(logic.values.metricsLoading).toBe(true)
        await refreshedMetricsSent
        expect(logic.values.rows.find((row) => row.id === 'wf-renewal')?.last7Days).toEqual({ succeeded: 3, failed: 2 })

        answerRefreshedMetrics()
        await expectLogic(logic).toDispatchActions(['loadMetricsSuccess'])
        expect(logic.values.rows.find((row) => row.id === 'wf-renewal')).toMatchObject({
            health: 'healthy',
            last7Days: { succeeded: 9, failed: 0 },
        })
    })

    it('keeps the list and skips the error toast when the metrics fail', async () => {
        metricsResponse = async () => [500, { detail: 'Server error' }]
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await act(async () => {
            await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])
        })
        expect(logic.values).toMatchObject({ metrics: null, metricsLoading: false, loadFailed: false })
        expect(shownIds(logic)).toHaveLength(5)
        expect(screen.queryByRole('alert')).toBeNull()
    })

    it.each([
        [urls.workflows(), 'the list opens', false],
        [urls.workflows('workflows'), 'the list opens', false],
        [urls.workflows(), 'the list is already open', true],
    ])(
        'moves old filter params on %s into q and text, replacing the history entry, when %s',
        async (pathname, _, alreadyOpen) => {
            logic = workflowsListV2Logic()
            if (alreadyOpen) {
                router.actions.push(pathname, { q: 'tag:old' })
                logic.mount()
            }
            router.actions.push(pathname, {
                status: 'active',
                type: 'loop',
                trigger_type: 'schedule',
                created_by: FIXTURE_USERS.lin.uuid,
                tags: '["growth","vip"]',
                search: 'renew',
                page: '3',
                other: 'kept',
            })
            if (!alreadyOpen) {
                logic.mount()
            }

            expect(router.values.location.pathname).toEqual(`/project/${MOCK_DEFAULT_TEAM.id}${pathname}`)
            expect(router.values.searchParams).toEqual({
                q: `status:active kind:loop trigger:schedule createdBy:${FIXTURE_USERS.lin.uuid} tag:growth tag:vip`,
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
                    { facet: 'tag', value: 'growth', negated: false },
                    { facet: 'tag', value: 'vip', negated: false },
                ],
                text: 'renew',
            })
        }
    )

    it('filters by tag pills, matching any of them', async () => {
        router.actions.push(urls.workflows('workflows'), { q: 'tag:growth tag:vip' })
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        expect(shownIds(logic)).toEqual(['wf-welcome', 'wf-sync'])
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

    it('sends no search when the text is cleared before the debounce ends', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setValue({ filters: [], text: 'renewal' })
            logic.actions.setValue({ filters: [], text: '' })
        }).toFinishAllListeners()
        expect(workflowRequests.map((params) => params.get('search')).filter(Boolean)).toEqual([])
    })

    it.each([
        ['clearing the text', (): void => logic.actions.setValue({ filters: [], text: '' })],
        ['clearing the filters', (): void => logic.actions.clearFilters()],
        ['leaving the list', (): void => logic.unmount()],
    ])('aborts a running search on %s', async (_, leave) => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        let markSent: () => void = () => {}
        const sent = new Promise<void>((resolve) => {
            markSent = resolve
        })
        serverSearch = () => {
            markSent()
            return new Promise(() => {})
        }

        logic.actions.setValue({ filters: [], text: 'renewal' })
        await sent
        leave()

        expect(searchSignals.map((signal) => signal.aborted)).toEqual([true])
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
        await act(async () => {
            await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'renewal' })).toDispatchActions([
                'searchWorkflowsSuccess',
            ])
        })
        expect(logic.values.serverSearchStatus).toEqual('failed')
        expect(shownIds(logic)).toEqual(['wf-renewal'])
        expect(screen.queryByRole('alert')).toBeNull()
    })

    it('fails a stalled server search at its deadline and aborts it, and a new search for the text succeeds', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        serverSearch = () => new Promise(() => {})
        jest.useFakeTimers()
        try {
            logic.actions.setValue({ filters: [], text: 'invoice' })
            await jest.advanceTimersByTimeAsync(1000 + SUMMARY_REQUEST_TIMEOUT_MS)
            expect(logic.values.serverSearchStatus).toEqual('failed')
            expect(searchSignals.map((signal) => signal.aborted)).toEqual([true])
        } finally {
            jest.useRealTimers()
        }

        serverSearch = async () => ['wf-sync']
        logic.actions.setValue({ filters: [], text: '' })
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'invoice' })).toFinishAllListeners()
        expect(logic.values.serverSearchStatus).toEqual('done')
        expect(shownIds(logic)).toEqual(['wf-sync'])
    })

    const RENEWAL_ACTIONS = [
        { id: 'trigger_node', name: 'Trigger', type: 'trigger', config: { type: 'event', filters: {} } },
        { id: 'action_email', name: 'Send reminder', type: 'function_email', config: { inputs: {} } },
        { id: 'exit_node', name: 'Exit', type: 'exit', config: { reason: 'Default exit' } },
    ]
    const RENEWAL_EDGES = [
        { from: 'trigger_node', to: 'action_email', type: 'continue' },
        { from: 'action_email', to: 'exit_node', type: 'continue' },
    ]

    it.each([
        [
            'succeeds',
            200,
            [
                expect.objectContaining({
                    name: 'Renewal reminder (copy)',
                    status: 'draft',
                    actions: RENEWAL_ACTIONS,
                    edges: RENEWAL_EDGES,
                }),
            ],
        ],
        ['fails', 500, []],
    ])('sends one duplicate at a time and clears the pending state when the copy %s', async (_, status, posted) => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess', 'loadMetricsSuccess'])

        let answerRetrieve: () => void = () => {}
        const postedBodies: Record<string, unknown>[] = []
        const retrieveSent = new Promise<void>((markSent) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_flows/summaries/': () => [200, paginated(FIXTURE_WORKFLOWS)],
                    '/api/projects/:team_id/hog_flows/:id/': () =>
                        new Promise((resolve) => {
                            answerRetrieve = () =>
                                resolve(
                                    status === 200
                                        ? [
                                              200,
                                              {
                                                  ...FIXTURE_WORKFLOWS[1],
                                                  status: 'active',
                                                  actions: RENEWAL_ACTIONS,
                                                  edges: RENEWAL_EDGES,
                                              },
                                          ]
                                        : [500, {}]
                                )
                            markSent()
                        }),
                },
                post: {
                    '/api/projects/:team_id/hog_flows/': async ({ request }) => {
                        postedBodies.push((await request.json()) as Record<string, unknown>)
                        return [200, { id: `wf-copy-${postedBodies.length}` }]
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
        expect(postedBodies).toEqual(posted)
        expect(logic.values.pendingRowActions).toEqual({})
    })

    it('stops paging an older load once a newer load starts', async () => {
        const requestedOffsets: string[] = []
        const heldFirstPages: Array<() => void> = []
        let markHeld: () => void = () => {}
        const nextHeld = (): Promise<void> => new Promise((resolve) => (markHeld = resolve))
        let held = nextHeld()
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flows/summaries/': ({ request }) => {
                    const offset = new URL(request.url).searchParams.get('offset') ?? '0'
                    requestedOffsets.push(offset)
                    if (offset !== '0') {
                        return [200, paginated([buildWorkflowRow({ id: 'wf-second-page' })])]
                    }
                    return new Promise((resolve) => {
                        heldFirstPages.push(() =>
                            resolve([
                                200,
                                paginated(
                                    [buildWorkflowRow({ id: 'wf-first-page' })],
                                    'http://localhost/api/projects/997/hog_flows/summaries/?limit=500&offset=500'
                                ),
                            ])
                        )
                        markHeld()
                    })
                },
            },
        })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await held
        held = nextHeld()
        logic.actions.loadWorkflows()
        await held

        // The older load gets its first page first, so without the stop it asks for page two before the newer load ends.
        heldFirstPages[0]()
        heldFirstPages[1]()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        expect(requestedOffsets).toEqual(['0', '0', '500'])
        expect(logic.values.rows.map((row) => row.id)).toEqual(['wf-first-page', 'wf-second-page'])
    })

    it('keeps row changes made while a reload is in flight', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])
        let answerReload: () => void = () => {}
        const reloadSent = new Promise<void>((markSent) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_flows/summaries/': () =>
                        new Promise((resolve) => {
                            answerReload = () => resolve([200, paginated(FIXTURE_WORKFLOWS)])
                            markSent()
                        }),
                },
            })
        })

        logic.actions.loadWorkflows()
        await reloadSent
        logic.actions.patchWorkflow('wf-renewal', { status: 'active' })
        logic.actions.removeWorkflow('wf-old-promo')
        answerReload()
        await expectLogic(logic).toDispatchActions(['loadWorkflowsSuccess'])

        expect(logic.values.workflows?.find((workflow) => workflow.id === 'wf-renewal')?.status).toEqual('active')
        expect(logic.values.workflows?.map((workflow) => workflow.id)).not.toContain('wf-old-promo')
    })

    it.each([
        ['a duplicate', (row: WorkflowListRow) => logic.actions.duplicateWorkflow(row)],
        [
            'a Customer.io import',
            () => {
                customerioImportLogic.mount()
                customerioImportLogic.actions.runImportSuccess({
                    content_fetched: true,
                    dryRun: false,
                    results: [],
                    segment_cohorts: [],
                })
            },
        ],
    ])('shows a new workflow from %s that only the server search matches', async (_, create) => {
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

        create(logic.values.rows.find((row) => row.id === 'wf-sync')!)
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
