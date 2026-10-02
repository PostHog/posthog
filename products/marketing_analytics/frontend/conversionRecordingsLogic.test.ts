import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { conversionRecordingsLogic } from './conversionRecordingsLogic'
import { ConversionRecordingsRequestApi } from './generated/api.schemas'

describe('conversionRecordingsLogic', () => {
    let logic: ReturnType<typeof conversionRecordingsLogic.build>
    const request: ConversionRecordingsRequestApi = {
        source: { kind: 'MarketingAnalyticsTableQuery', properties: [] },
        goal_id: 'purchase',
        group: 'winter-sale',
    }
    const first = '00000000-0000-4000-8000-000000000001'
    const second = '00000000-0000-4000-8000-000000000002'
    let requests: ConversionRecordingsRequestApi[]

    beforeEach(() => {
        initKeaTests()
        requests = []
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': async ({ request }) => {
                    const body = (await request.json()) as ConversionRecordingsRequestApi
                    requests.push(body)
                    return {
                        session_ids: body.after ? [second] : [first],
                        has_more: !body.after,
                        preparing: false,
                    }
                },
            },
        })
        logic = conversionRecordingsLogic({ request })
    })
    afterEach(() => logic.unmount())

    it('appends sessions and starts over when reloading', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(requests[0].client_query_id).toEqual(expect.any(String))
        await expectLogic(logic, () => logic.actions.loadSessions({ append: true }))
            .toFinishAllListeners()
            .toMatchValues({ page: partial({ session_ids: [first, second] }) })
        expect(requests[1]).toMatchObject({ ...request, after: first })
        await expectLogic(logic, () => logic.actions.loadSessions({}))
            .toFinishAllListeners()
            .toMatchValues({ page: partial({ session_ids: [first], has_more: true }) })
        expect(requests[2]).not.toHaveProperty('after')
    })

    it.each([false, true])('preserves loaded pages and retries failures (append: %s)', async (append) => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': async ({ request }) => {
                    requests.push((await request.json()) as ConversionRecordingsRequestApi)
                    return [500, { detail: 'Failed' }]
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadSessions({ append })
        })
            .toFinishAllListeners()
            .toMatchValues({
                page: partial({ failed: true, session_ids: append ? [first] : [], has_more: append }),
                pageLoading: false,
            })
        expect(logic.values.page.queryId).toBe(requests.at(-1)?.client_query_id)
        expect(logic.values.page.queryId).not.toBe(requests[0].client_query_id)
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': {
                    session_ids: [second],
                    preparing: false,
                    has_more: false,
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadSessions({ append: logic.values.page.has_more }))
            .toFinishAllListeners()
            .toMatchValues({
                page: partial({ session_ids: append ? [first, second] : [second], preparing: false }),
                pageLoading: false,
            })
        expect(logic.values.page.failed).toBeUndefined()
        expect(logic.values.page.queryId).toBeUndefined()
    })
})
