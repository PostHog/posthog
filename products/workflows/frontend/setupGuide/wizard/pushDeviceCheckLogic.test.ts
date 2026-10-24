import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { useMocks } from '~/mocks/jest'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { IntegrationType } from '~/types'

import { pushDeviceCheckLogic } from './pushDeviceCheckLogic'

const PUSH_INTEGRATIONS = [
    {
        id: 1,
        kind: 'apns',
        display_name: 'APNs',
        icon_url: '',
        created_at: '',
        config: { bundle_id: 'com.example.app' },
    },
    {
        id: 2,
        kind: 'firebase',
        display_name: 'Firebase',
        icon_url: '',
        created_at: '',
        config: { project_id: 'example-project' },
    },
] as IntegrationType[]

function deferredCount(): { promise: Promise<HogQLQueryResponse>; resolve: (count: number) => void } {
    let resolve: (count: number) => void = () => {}
    const promise = new Promise<HogQLQueryResponse>((res) => {
        resolve = (count) => res({ results: [[count]] } as HogQLQueryResponse)
    })
    return { promise, resolve }
}

describe('pushDeviceCheckLogic', () => {
    let logic: ReturnType<typeof pushDeviceCheckLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': { results: PUSH_INTEGRATIONS, next: null },
                '/api/projects/:project_id/integrations': { results: PUSH_INTEGRATIONS, next: null },
            },
        })
        initKeaTests()
        jest.useFakeTimers()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('drops a count for the old platform that arrives after switching platforms', async () => {
        const iosQuery = deferredCount()
        const androidQuery = deferredCount()
        jest.spyOn(api, 'queryHogQL')
            .mockReturnValueOnce(iosQuery.promise)
            .mockReturnValueOnce(androidQuery.promise)
            .mockImplementation(() => new Promise(() => {}))

        logic = pushDeviceCheckLogic()
        logic.mount()
        await expectLogic(logic, () => {
            integrationsLogic.actions.loadIntegrationsSuccess(PUSH_INTEGRATIONS)
        }).toDispatchActions(['loadRegisteredDeviceCount'])
        expect(logic.values.platform).toEqual('ios')

        logic.actions.setPlatform('android')
        androidQuery.resolve(0)
        await expectLogic(logic).toDispatchActions(['loadRegisteredDeviceCountSuccess'])
        iosQuery.resolve(3)
        await Promise.resolve()
        await Promise.resolve()

        expect(logic.values).toMatchObject({ platform: 'android', registeredDeviceCount: 0, deviceRegistered: false })
    })

    it('starts the next device check only after the previous one returns', async () => {
        const slowQuery = deferredCount()
        const queryHogQL = jest
            .spyOn(api, 'queryHogQL')
            .mockReturnValueOnce(slowQuery.promise)
            .mockImplementation(() => new Promise(() => {}))

        logic = pushDeviceCheckLogic()
        logic.mount()
        await expectLogic(logic, () => {
            integrationsLogic.actions.loadIntegrationsSuccess(PUSH_INTEGRATIONS)
        }).toDispatchActions(['loadRegisteredDeviceCount'])

        jest.advanceTimersByTime(30_000)
        expect(queryHogQL).toHaveBeenCalledTimes(1)

        slowQuery.resolve(0)
        await expectLogic(logic).toDispatchActions(['loadRegisteredDeviceCountSuccess'])
        jest.advanceTimersByTime(5_000)
        expect(queryHogQL).toHaveBeenCalledTimes(2)
    })
})
