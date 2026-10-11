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

    it('replaces the session page and navigates back with the matching cursor', async () => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        expect(requests[0].client_query_id).toEqual(expect.any(String))
        await expectLogic(logic, () => logic.actions.loadSessions({ pageIndex: 1 }))
            .toFinishAllListeners()
            .toMatchValues({ page: partial({ session_ids: [second], pageIndex: 1, has_more: false }) })
        expect(requests[1]).toMatchObject({ ...request, after: first })
        await expectLogic(logic, () => logic.actions.loadSessions({ pageIndex: 0 }))
            .toFinishAllListeners()
            .toMatchValues({ page: partial({ session_ids: [first], has_more: true, pageIndex: 0 }) })
        expect(requests[2]).not.toHaveProperty('after')
        await expectLogic(logic, () => logic.actions.loadSessions({ pageIndex: 1 })).toFinishAllListeners()
        expect(requests[3].after).toBe(first)
    })

    it.each(['failed', 'preparing'] as const)('preserves the current page and retries the %s page', async (state) => {
        await expectLogic(logic, () => {
            logic.mount()
        }).toFinishAllListeners()
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': async ({ request }) => {
                    requests.push((await request.json()) as ConversionRecordingsRequestApi)
                    return state === 'failed'
                        ? [500, { detail: 'Failed' }]
                        : { session_ids: [], has_more: false, preparing: true }
                },
            },
        })
        await expectLogic(logic, () => {
            logic.actions.loadSessions({ pageIndex: 1 })
        })
            .toFinishAllListeners()
            .toMatchValues({
                page: partial({ preparing: state === 'preparing', session_ids: [first], has_more: true, pageIndex: 0 }),
                pageLoading: false,
            })
        expect(logic.values.page.queryId).toBe(requests.at(-1)?.client_query_id)
        expect(logic.values.page.queryId).not.toBe(requests[0].client_query_id)
        expect(logic.values.page.errorMessage).toBe(state === 'failed' ? 'Failed' : undefined)
        useMocks({
            post: {
                '/api/projects/:team_id/marketing_analytics/conversion_recordings/': async ({ request }) => {
                    requests.push((await request.json()) as ConversionRecordingsRequestApi)
                    return { session_ids: [second], preparing: false, has_more: false }
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadSessions({ pageIndex: logic.values.page.retryPage }))
            .toFinishAllListeners()
            .toMatchValues({
                page: partial({ session_ids: [second], preparing: false, pageIndex: 1 }),
                pageLoading: false,
            })
        expect(logic.values.page.errorMessage).toBeUndefined()
        expect(logic.values.page.queryId).toBeUndefined()
        expect(requests.at(-1)?.after).toBe(first)
    })
})
