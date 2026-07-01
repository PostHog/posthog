import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'

import { initKeaTests } from '~/test/init'

import { rateLimitConfigLogic } from './rateLimitConfigLogic'

describe('rateLimitConfigLogic', () => {
    let logic: ReturnType<typeof rateLimitConfigLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = rateLimitConfigLogic()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('surfaces a no-access state on a 403 without rethrowing or loading the volume chart', async () => {
        jest.spyOn(api.errorTracking, 'getSettings').mockRejectedValue(new ApiError('Forbidden', 403))
        const querySpy = jest.spyOn(api, 'query')

        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadConfig', 'setNoAccess', 'loadConfigSuccess'])
            .toNotHaveDispatchedActions(['loadConfigFailure', 'loadVolume'])
            .toMatchValues({ noAccess: true, config: null })

        expect(querySpy).not.toHaveBeenCalled()
    })

    it('loads the volume chart when the settings request succeeds', async () => {
        jest.spyOn(api.errorTracking, 'getSettings').mockResolvedValue({
            project_rate_limit_value: 100,
            project_rate_limit_bucket_size_minutes: 60,
        } as any)
        jest.spyOn(api, 'query').mockResolvedValue({ results: [] } as any)

        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadConfigSuccess', 'loadVolume'])
            .toMatchValues({ noAccess: false })
    })
})
