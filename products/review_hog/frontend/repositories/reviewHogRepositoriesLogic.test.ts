import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ReviewRepositoryOverviewEntryApi } from 'products/review_hog/frontend/generated/api.schemas'

import { reviewHogRepositoriesLogic } from './reviewHogRepositoriesLogic'

const ROSE = { id: 202, uuid: 'user-202', email: 'rose@example.com', hedgehog_config: null }

function entry(overrides: Partial<ReviewRepositoryOverviewEntryApi>): ReviewRepositoryOverviewEntryApi {
    return {
        full_name: 'example-org/web',
        github_repo_id: 1001,
        owner: 'this_project',
        owner_project: null,
        in_project: true,
        selected: false,
        repository_id: null,
        exception: null,
        my_choice: null,
        my_choice_id: null,
        my_result: { flash: true, reason: 'project_everyone' },
        inherited_result: { flash: true, reason: 'project_everyone' },
        ...overrides,
    }
}

describe('reviewHogRepositoriesLogic', () => {
    let logic: ReturnType<typeof reviewHogRepositoriesLogic.build>
    let requests: string[]
    let overviewCalls: number
    let overviewTotal: number

    beforeEach(() => {
        requests = []
        overviewCalls = 0
        overviewTotal = 0
        useMocks({
            get: {
                '/api/projects/:team_id/review_hog/project_settings/': () => [
                    200,
                    {
                        flash_for: 'everyone',
                        bot_prs: 'skip',
                        people: [{ id: 'person-rose', user: ROSE, kind: 'excepted' }],
                        installations: [
                            {
                                installation_id: '41',
                                account_name: 'example-org',
                                connected_by: null,
                                claim_id: 'claim-1',
                                scope: 'all',
                                all_taken_by_project: null,
                            },
                        ],
                        can_edit: true,
                    },
                ],
                '/api/projects/:team_id/review_hog/repository_overview/': () => {
                    overviewCalls += 1
                    return [
                        200,
                        {
                            installation_id: '41',
                            claim_scope: 'all',
                            results: [],
                            total: overviewTotal,
                            has_more: false,
                            next_offset: null,
                        },
                    ]
                },
                '/api/projects/:team_id/review_hog/settings/': () => [200, { default_review_mode: 'follow' }],
            },
            post: {
                '/api/projects/:team_id/review_hog/repository_choices/': async ({ request }) => {
                    requests.push(`POST choice ${JSON.stringify(await request.json())}`)
                    return [200, { choice: null, my_result: { flash: false, reason: 'own_repository_choice' } }]
                },
                '/api/projects/:team_id/review_hog/repositories/': async ({ request }) => {
                    requests.push(`POST repository ${JSON.stringify(await request.json())}`)
                    return [200, { repository: { id: 'repo-web' }, taken_from_project: null }]
                },
                '/api/projects/:team_id/review_hog/repositories/:id/people/': async ({ request, params }) => {
                    requests.push(`POST person ${params.id} ${JSON.stringify(await request.json())}`)
                    return [201, {}]
                },
            },
            patch: {
                '/api/projects/:team_id/review_hog/settings/': async ({ request }) => [200, await request.json()],
            },
            delete: {
                '/api/projects/:team_id/review_hog/repository_choices/:id/': ({ params }) => {
                    requests.push(`DELETE choice ${params.id}`)
                    return [204]
                },
            },
        })
        initKeaTests()
        logic = reviewHogRepositoriesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        {
            name: 'follow clears a stored choice',
            entry: entry({ my_choice: 'off', my_choice_id: 'choice-1' }),
            value: 'follow' as const,
            expected: ['DELETE choice choice-1'],
        },
        {
            name: 'follow without a stored choice writes nothing',
            entry: entry({}),
            value: 'follow' as const,
            expected: [],
        },
        {
            name: 'the opposite of the inherited value is stored',
            entry: entry({}),
            value: 'off' as const,
            expected: [
                'POST choice {"installation_id":"41","full_name":"example-org/web","github_repo_id":1001,"mode":"off"}',
            ],
        },
    ])('my choice: $name', async ({ entry: picked, value, expected }) => {
        await expectLogic(logic).toDispatchActions(['loadOverviewSuccess'])

        await expectLogic(logic, () => logic.actions.setMyChoice(picked, value)).toFinishAllListeners()

        expect(requests).toEqual(expected)
    })

    it('a new exception starts as a copy of the project rule and its list', async () => {
        await expectLogic(logic).toDispatchActions(['loadOverviewSuccess'])

        await expectLogic(logic, () => logic.actions.addException(entry({}))).toFinishAllListeners()

        expect(requests).toEqual([
            'POST repository {"installation_id":"41","full_name":"example-org/web","github_repo_id":1001,"flash_for":"everyone"}',
            'POST person repo-web {"user_id":202,"kind":"excepted"}',
        ])
    })

    it('changing my default reloads the list, because the default decides every inherited result', async () => {
        await expectLogic(logic).toDispatchActions(['loadOverviewSuccess'])
        const callsBefore = overviewCalls

        await expectLogic(logic, () => logic.actions.setMyDefault('off')).toDispatchActions([
            'updateSettingsSuccess',
            'loadOverview',
            'loadOverviewSuccess',
        ])
        expect(overviewCalls).toBe(callsBefore + 1)
    })

    it('goes back to the last page with rows when a write empties the current one', async () => {
        overviewTotal = 21
        await expectLogic(logic, () => logic.actions.setPage(1)).toDispatchActions(['loadOverviewSuccess'])
        expect(logic.values.page).toBe(1)

        overviewTotal = 20
        await expectLogic(logic, () => logic.actions.loadOverview()).toFinishAllListeners()

        expect(logic.values.page).toBe(0)
    })
})
