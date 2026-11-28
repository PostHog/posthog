import { expectLogic } from 'kea-test-utils'

import { ApiError, NetworkError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import * as api from 'products/signals/frontend/generated/api'

import { scoutNamesLogic } from './scoutNamesLogic'

describe('scoutNamesLogic', () => {
    let logic: ReturnType<typeof scoutNamesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = scoutNamesLogic()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['a server error', new ApiError('A server error occurred.', 500)],
        ['a network error', new NetworkError('network')],
    ])('falls back to default scout names after %s', async (_, error) => {
        jest.spyOn(api, 'signalsScoutConfigList').mockRejectedValueOnce(error)

        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadScoutConfigsSuccess'])
            .toMatchValues({ scoutConfigs: null, scoutConfigsLoading: false })
    })
})
