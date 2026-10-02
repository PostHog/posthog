import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { conversionPeopleLogic } from './conversionPeopleLogic'
import { ConversionPeopleRequestApi } from './generated/api.schemas'

describe('conversionPeopleLogic', () => {
    let logic: ReturnType<typeof conversionPeopleLogic.build>
    const request: ConversionPeopleRequestApi = {
        source: { kind: 'MarketingAnalyticsTableQuery', properties: [] },
        goal_id: 'purchase',
        group: 'winter-sale',
    }
    const first = { id: '00000000-0000-4000-8000-000000000001', name: 'alex@example.com' }
    const second = { id: '00000000-0000-4000-8000-000000000002', name: 'sam@example.com' }
    let requests: ConversionPeopleRequestApi[]

    beforeEach(() => {
        initKeaTests()
        requests = []
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_people/': async ({ request }) => {
                    const body = (await request.json()) as ConversionPeopleRequestApi
                    requests.push(body)
                    return {
                        results: body.offset || body.search ? [second] : [first],
                        has_more: !body.offset && !body.search,
                        preparing: false,
                    }
                },
            },
        })
        logic = conversionPeopleLogic({ request })
    })
    afterEach(() => logic.unmount())

    it('appends pages but replaces them when searching', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.loadPeople({ append: true }))
            .toFinishAllListeners()
            .toMatchValues({ page: partial({ results: [first, second] }) })
        expect(requests[1]).toMatchObject({ ...request, offset: 1 })
        await expectLogic(logic, () => logic.actions.setSearch('sam'))
            .toFinishAllListeners()
            .toMatchValues({ page: partial({ results: [second], has_more: false }) })
        expect(requests[2]).toMatchObject({ ...request, offset: 0, search: 'sam' })
    })

    it.each([false, true])('preserves loaded pages and retries failures (append: %s)', async (append) => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        useMocks({
            post: { '/api/projects/:team_id/marketing_analytics/conversion_people/': [500, { detail: 'Failed' }] },
        })
        await expectLogic(logic, () => {
            logic.actions.loadPeople({ append })
        })
            .toFinishAllListeners()
            .toMatchValues({
                page: partial({ failed: true, results: append ? [first] : [], has_more: append }),
                pageLoading: false,
            })
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_people/': {
                    results: [second],
                    preparing: false,
                    has_more: false,
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadPeople({ append: logic.values.page.has_more }))
            .toFinishAllListeners()
            .toMatchValues({
                page: partial({ results: append ? [first, second] : [second], preparing: false }),
                pageLoading: false,
            })
        expect(logic.values.page.failed).toBeUndefined()
    })
})
