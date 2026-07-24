import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { serviceFilterLogic } from './serviceFilterLogic'

describe('serviceFilterLogic', () => {
    let logic: ReturnType<typeof serviceFilterLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    it('loads service names from the values endpoint', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/logs/values': () => [
                    200,
                    { results: [{ name: 'api' }, { name: 'worker' }] },
                ],
            },
        })
        initKeaTests()
        logic = serviceFilterLogic({})
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ serviceNames: ['api', 'worker'] })
    })

    it.each([
        ['a 500 response', () => [500, { detail: 'A server error occurred.' }]],
        ['a null response body', () => [200, null]],
    ])('degrades to an empty list on %s instead of throwing', async (_label, handler) => {
        useMocks({ get: { '/api/environments/:team_id/logs/values': handler as any } })
        initKeaTests()
        logic = serviceFilterLogic({})
        logic.mount()

        // The loader must resolve (Success) rather than reject (Failure); a rejected
        // loader is what surfaced the uncaught error to the user.
        await expectLogic(logic)
            .toDispatchActions(['loadServiceNamesSuccess'])
            .toNotHaveDispatchedActions(['loadServiceNamesFailure'])
            .toMatchValues({ serviceNames: [] })
    })
})
