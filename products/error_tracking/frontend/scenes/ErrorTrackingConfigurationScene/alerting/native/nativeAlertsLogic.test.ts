import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    errorTrackingAlertsDestroy,
    errorTrackingAlertsList,
    errorTrackingAlertsPartialUpdate,
} from '../../../../generated/api'
import { ErrorTrackingAlertApi } from '../../../../generated/api.schemas'
import { nativeAlertsLogic } from './nativeAlertsLogic'

jest.mock('../../../../generated/api', () => ({
    errorTrackingAlertsList: jest.fn(),
    errorTrackingAlertsPartialUpdate: jest.fn(),
    errorTrackingAlertsDestroy: jest.fn(),
}))

const mockList = jest.mocked(errorTrackingAlertsList)
const mockPartialUpdate = jest.mocked(errorTrackingAlertsPartialUpdate)
const mockDestroy = jest.mocked(errorTrackingAlertsDestroy)

function alert(overrides: Partial<ErrorTrackingAlertApi> = {}): ErrorTrackingAlertApi {
    return {
        id: 'alert-1',
        name: 'Production errors',
        enabled: true,
        triggers: ['issue_created'],
        filters: {},
        throttle_seconds: 0,
        destinations: [],
        created_at: '2026-09-01T00:00:00Z',
        updated_at: '2026-09-01T00:00:00Z',
        ...overrides,
    } as ErrorTrackingAlertApi
}

describe('nativeAlertsLogic', () => {
    let logic: ReturnType<typeof nativeAlertsLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockList.mockResolvedValue({ count: 2, results: [alert(), alert({ id: 'alert-2', name: 'Spikes' })] } as never)
        logic = nativeAlertsLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('loads alerts, toggles one in place and removes a deleted one', async () => {
        await expectLogic(logic, () => logic.actions.loadAlerts())
            .toDispatchActions(['loadAlertsSuccess'])
            .toMatchValues({ alerts: [alert(), alert({ id: 'alert-2', name: 'Spikes' })] })

        mockPartialUpdate.mockResolvedValue(alert({ enabled: false }))
        await expectLogic(logic, () =>
            logic.actions.setAlertEnabled({ alert: alert(), enabled: false })
        ).toDispatchActions(['setAlertEnabledSuccess'])
        expect(mockPartialUpdate).toHaveBeenCalledWith(expect.any(String), 'alert-1', { enabled: false })
        expect(logic.values.alerts.map((a) => [a.id, a.enabled])).toEqual([
            ['alert-1', false],
            ['alert-2', true],
        ])

        mockDestroy.mockResolvedValue(undefined)
        await expectLogic(logic, () =>
            logic.actions.deleteAlert({ alert: alert({ id: 'alert-2' }) })
        ).toDispatchActions(['deleteAlertSuccess'])
        expect(logic.values.alerts.map((a) => a.id)).toEqual(['alert-1'])
    })
})
