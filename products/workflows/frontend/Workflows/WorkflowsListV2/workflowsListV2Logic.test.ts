import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { EmailTemplateRow, WorkflowRow } from './workflowListRows'
import {
    FIXTURE_TEMPLATES,
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

    beforeEach(() => {
        workflowRequests = []
        serverSearch = async () => []
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
                        const ids = await serverSearch(search)
                        return [200, paginated(ids.map((id) => byId.get(id)!))]
                    }
                    if (params.get('offset') === '1000') {
                        return [200, paginated(secondPage)]
                    }
                    return [
                        200,
                        paginated(
                            FIXTURE_WORKFLOWS,
                            'http://localhost/api/projects/997/hog_flows/summaries/?limit=1000&offset=1000'
                        ),
                    ]
                },
                '/api/projects/:team_id/messaging_templates/summaries/': () => [200, paginated(FIXTURE_TEMPLATES)],
            },
        })
        initKeaTests()
    })

    afterEach(() => logic?.unmount())

    it('loads every page of workflows plus the email templates, newest first', async () => {
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadListSuccess'])
        expect(shownIds(logic)).toEqual([
            'wf-welcome',
            'wf-page-two',
            'tpl-receipt',
            'wf-renewal',
            'wf-sync',
            'tpl-newsletter',
            'wf-old-promo',
        ])
        expect(
            workflowRequests.map((params) => [params.get('limit'), params.get('offset'), params.get('type')])
        ).toEqual([
            ['1000', null, 'messaging,automation,loop'],
            ['1000', '1000', 'messaging,automation,loop'],
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
                            'http://localhost/api/projects/997/hog_flows/summaries/?limit=1000&offset=1000'
                        ),
                    ]
                },
            },
        })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadListFailure'])
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
                '/api/projects/:team_id/messaging_templates/summaries/': record(paginated(FIXTURE_TEMPLATES)),
                '/api/projects/:team_id/hog_flows/:id/': record({ ...FIXTURE_WORKFLOWS[0], actions: [], edges: [] }),
            },
            post: { '/api/projects/:team_id/hog_flows/': record({}) },
            patch: {
                '/api/projects/:team_id/hog_flows/:id/': record({}),
                '/api/projects/:team_id/messaging_templates/:id': record({}),
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: TEAM_ID })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadListSuccess'])

        const workflow = logic.values.rows.find((row) => row.id === 'wf-renewal') as WorkflowRow
        const template = logic.values.rows.find((row) => row.id === 'tpl-receipt') as EmailTemplateRow
        await expectLogic(logic, () => logic.actions.toggleWorkflowStatus(workflow)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.duplicateWorkflow(workflow)).toDispatchActions(['loadListSuccess'])
        await expectLogic(logic, () => logic.actions.deleteTemplate(template)).toFinishAllListeners()

        expect(paths.filter((path) => !path.includes(`/projects/${TEAM_ID}/`))).toEqual([])
        expect(new Set(paths)).toEqual(
            new Set([
                `GET /api/projects/${TEAM_ID}/hog_flows/summaries/`,
                `GET /api/projects/${TEAM_ID}/messaging_templates/summaries/`,
                `PATCH /api/projects/${TEAM_ID}/hog_flows/wf-renewal/`,
                `GET /api/projects/${TEAM_ID}/hog_flows/wf-renewal/`,
                `POST /api/projects/${TEAM_ID}/hog_flows/`,
                `PATCH /api/projects/${TEAM_ID}/messaging_templates/tpl-receipt/`,
            ])
        )
    })

    it('shows a load error instead of an empty list', async () => {
        useMocks({ get: { '/api/projects/:team_id/hog_flows/summaries/': () => [500, { detail: 'Boom' }] } })
        router.actions.push(urls.workflows())
        logic = workflowsListV2Logic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadListFailure'])
        expect(logic.values.loadFailed).toBe(true)
        expect(logic.values.listLoaded).toBe(false)
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
        router.actions.push(urls.workflows(), { q: 'kind:workflow' })
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadListSuccess'])

        router.actions.push(router.values.location.pathname, { ...router.values.searchParams, page: 2 })
        expect(router.values.searchParams).toEqual({ q: 'kind:workflow', page: 2 })
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

    it.each([
        ['removes the row once the delete succeeds', 200, ['tpl-newsletter']],
        ['keeps the row when the delete fails', 500, ['tpl-receipt', 'tpl-newsletter']],
    ])('deleteTemplate %s', async (_, status, expected) => {
        useMocks({
            patch: {
                '/api/projects/:team_id/messaging_templates/:id': () => [
                    status,
                    status === 200 ? {} : { detail: 'No' },
                ],
            },
        })
        router.actions.push(urls.workflows(), { q: 'kind:email-template' })
        logic = workflowsListV2Logic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadListSuccess'])

        const receipt = logic.values.rows.find((row) => row.id === 'tpl-receipt')!
        await expectLogic(logic, () => logic.actions.deleteTemplate(receipt as any)).toFinishAllListeners()
        expect(shownIds(logic)).toEqual(expected)
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
        await expectLogic(logic).toDispatchActions(['loadListSuccess'])

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
            return Promise.resolve(search === 'renews' ? ['wf-sync'] : [])
        }

        logic.actions.setValue({ filters: [], text: 'spring' })
        await slowSearchSent
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'renews' })).toDispatchActions([
            'searchWorkflowsSuccess',
        ])
        // Only the client match on the name, plus the workflow the server found in an email body.
        expect(shownIds(logic)).toEqual(['wf-renewal', 'wf-sync'])

        answerSlowSearch(['wf-old-promo'])
        await expectLogic(logic).toFinishAllListeners()
        expect(shownIds(logic)).toEqual(['wf-renewal', 'wf-sync'])
        expect(workflowRequests.map((params) => params.get('search')).filter(Boolean)).toEqual(['spring', 'renews'])

        // Back to the earlier text while a newer search is still out: the late answer must not replace it.
        let answerDetour: (ids: string[]) => void = () => {}
        let markDetourSent: () => void = () => {}
        const detourSent = new Promise<void>((resolve) => {
            markDetourSent = resolve
        })
        serverSearch = (search) => {
            if (search === 'renewsx') {
                markDetourSent()
                return new Promise((resolve) => {
                    answerDetour = resolve
                })
            }
            return Promise.resolve(search === 'renews' ? ['wf-sync'] : [])
        }
        logic.actions.setValue({ filters: [], text: 'renewsx' })
        await detourSent
        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 'renews' })).toDispatchActions([
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
        await expectLogic(logic).toDispatchActions(['loadListSuccess'])

        await expectLogic(logic, () => logic.actions.setValue({ filters: [], text: 're' })).toFinishAllListeners()
        expect(workflowRequests.map((params) => params.get('search')).filter(Boolean)).toEqual([])
    })
})
