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
        id: 3,
        kind: 'apns',
        display_name: 'APNs',
        icon_url: '',
        created_at: '',
        config: { bundle_id: 'com.example.other' },
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

    it('checks one app with a full count, then confirms its recent registrations, one check at a time', async () => {
        const slowQuery = deferredCount()
        const queryHogQL = jest
            .spyOn(api, 'queryHogQL')
            .mockReturnValueOnce(slowQuery.promise)
            .mockResolvedValue({ results: [[0]] } as HogQLQueryResponse)

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

        const [fullCount, recentCheck] = queryHogQL.mock.calls.map(([query]) => String(query))
        expect(logic.values.appId).toEqual('com.example.app')
        expect(fullCount).toContain('FROM persons')
        expect(recentCheck).toContain('FROM events')
        for (const query of [fullCount, recentCheck]) {
            expect(query).toContain("'$device_push_subscription_com.example.app'")
            expect(query).not.toContain('com.example.other')
        }
        await expectLogic(logic).toDispatchActions(['loadRegisteredDeviceCountSuccess'])

        // A registration event lands before its person row, which looks the same as a device that unsubscribed.
        const registrationEvents = 1
        let subscribedPersons = 0
        queryHogQL.mockImplementation((query) =>
            Promise.resolve({
                results: [[String(query).includes('FROM persons') ? subscribedPersons : registrationEvents]],
            } as HogQLQueryResponse)
        )
        const personScans = (): number =>
            queryHogQL.mock.calls.filter(([query]) => String(query).includes('FROM persons')).length
        const runCheck = async (): Promise<void> => {
            jest.advanceTimersByTime(30_000)
            await expectLogic(logic).toDispatchActions(['loadRegisteredDeviceCountSuccess'])
        }
        await runCheck()
        await runCheck()
        expect(personScans()).toEqual(2)
        expect(logic.values.deviceRegistered).toEqual(false)

        subscribedPersons = 1
        await runCheck()
        expect(personScans()).toEqual(3)
        expect(logic.values).toMatchObject({ registeredDeviceCount: 1, deviceRegistered: true })
    })
})
