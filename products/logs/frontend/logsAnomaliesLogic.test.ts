import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { logsAnomaliesSeriesBandsCreate } from 'products/logs/frontend/generated/api'

import { DEFAULT_VISIBLE_SERIES, logsAnomaliesLogic } from './logsAnomaliesLogic'

function seriesBandsResponse(seriesCount: number): Record<string, any> {
    return {
        service_name: 'checkout',
        window_start: '2026-08-10T10:00:00Z',
        window_end: '2026-08-17T10:00:00Z',
        interval_minutes: 60,
        series_truncated: false,
        series: Array.from({ length: seriesCount }, (_, index) => ({
            namespace: 'ns',
            environment: 'prod',
            severity: `severity-${index}`,
            total_count: 100 - index,
            baseline_weeks: 5,
            buckets: [],
        })),
    }
}

jest.mock('products/logs/frontend/generated/api', () => ({
    __esModule: true,
    logsAnomaliesSeriesBandsCreate: jest.fn(),
}))

describe('logsAnomaliesLogic', () => {
    let logic: ReturnType<typeof logsAnomaliesLogic.build>

    beforeEach(() => {
        initKeaTests()
        ;(logsAnomaliesSeriesBandsCreate as jest.Mock).mockResolvedValue(seriesBandsResponse(3))
        logic = logsAnomaliesLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    it('does not call the endpoint without a service', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSeriesBands()
        }).toFinishAllListeners()
        expect(logsAnomaliesSeriesBandsCreate).not.toHaveBeenCalled()
        expect(logic.values.seriesBands).toBeNull()
    })

    it('loads bands when a service is picked, and clears them on switch', async () => {
        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
        }).toFinishAllListeners()

        expect(logsAnomaliesSeriesBandsCreate).toHaveBeenCalledTimes(1)
        const [, body] = (logsAnomaliesSeriesBandsCreate as jest.Mock).mock.calls[0]
        expect(body.serviceName).toBe('checkout')
        expect(logic.values.seriesBands?.series).toHaveLength(3)

        // The previous service's charts must not linger under the new selection.
        await expectLogic(logic, () => {
            logic.actions.setServiceName(null)
        }).toFinishAllListeners()
        expect(logic.values.seriesBands).toBeNull()
        expect(logsAnomaliesSeriesBandsCreate).toHaveBeenCalledTimes(1)
    })

    it('slices visible series and grows the window on show more', async () => {
        ;(logsAnomaliesSeriesBandsCreate as jest.Mock).mockResolvedValue(
            seriesBandsResponse(DEFAULT_VISIBLE_SERIES + 3)
        )
        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
        }).toFinishAllListeners()

        expect(logic.values.visibleSeries).toHaveLength(DEFAULT_VISIBLE_SERIES)
        expect(logic.values.hiddenSeriesCount).toBe(3)

        logic.actions.showMoreSeries()
        expect(logic.values.visibleSeries).toHaveLength(DEFAULT_VISIBLE_SERIES + 3)
        expect(logic.values.hiddenSeriesCount).toBe(0)
    })
})
