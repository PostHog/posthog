import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsAnomaliesScanCreate, logsServicesCreate } from 'products/logs/frontend/generated/api'

import { logsAnomaliesLogic } from './logsAnomaliesLogic'

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsServicesCreate: jest.fn().mockResolvedValue({
        services: [
            { service_name: 'checkout', log_count: 100, error_count: 0, error_rate: 0 },
            { service_name: '(no service)', log_count: 5, error_count: 0, error_rate: 0 },
        ],
        sparkline: [],
    }),
    logsAnomaliesScanCreate: jest.fn().mockResolvedValue({
        service_name: 'checkout',
        eval_start: '2026-08-05T00:00:00Z',
        eval_end: '2026-08-06T00:00:00Z',
        lookback_days: 42,
        eval_clipped: false,
        degraded: false,
        binding_constraints: [],
        series: [],
        issues: [],
    }),
}))

describe('logsAnomaliesLogic', () => {
    let logic: ReturnType<typeof logsAnomaliesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = logsAnomaliesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('filters placeholder services out of the suggestions', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.serviceSuggestions).toEqual(['checkout'])
    })

    it('does not call the scan endpoint without a service', async () => {
        await expectLogic(logic, () => {
            logic.actions.runScan()
        }).toFinishAllListeners()
        expect(logsAnomaliesScanCreate).not.toHaveBeenCalled()
        expect(logic.values.scanDisabledReason).toBe('Pick a service to scan first')
    })

    it('scans with an absolute UTC window derived from the selected width', async () => {
        logic.actions.setServiceName('checkout')
        logic.actions.setWindowHours(6)
        await expectLogic(logic, () => {
            logic.actions.runScan()
        }).toFinishAllListeners()

        expect(logsAnomaliesScanCreate).toHaveBeenCalledTimes(1)
        const [, body] = (logsAnomaliesScanCreate as jest.Mock).mock.calls[0]
        expect(body.serviceName).toBe('checkout')
        const from = new Date(body.dateRange.date_from)
        const to = new Date(body.dateRange.date_to)
        // The endpoint requires absolute ISO datetimes; relative expressions
        // like "-6h" would be rejected.
        expect(Number.isNaN(from.getTime())).toBe(false)
        expect(to.getTime() - from.getTime()).toBe(6 * 60 * 60 * 1000)
        expect(logic.values.scanResult?.service_name).toBe('checkout')
    })

    it('keeps the previous result until a new scan succeeds', async () => {
        logic.actions.setServiceName('checkout')
        await expectLogic(logic, () => {
            logic.actions.runScan()
        }).toFinishAllListeners()
        const firstResult = logic.values.scanResult

        ;(logsServicesCreate as jest.Mock).mockClear()
        logic.actions.setServiceName('other-service')
        expect(logic.values.scanResult).toBe(firstResult)
    })
})
