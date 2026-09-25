import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
        const secondPage = [
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
