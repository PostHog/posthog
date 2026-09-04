import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { logsAnomaliesSeriesBandsCreate } from 'products/logs/frontend/generated/api'
import type { LogsSeriesBandsResponseApi } from 'products/logs/frontend/generated/api.schemas'

import { DEFAULT_VISIBLE_SERIES, logsAnomaliesLogic } from './logsAnomaliesLogic'

function seriesBandsResponse(seriesCount: number): LogsSeriesBandsResponseApi {
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
            history_start: '2026-07-13T10:00:00Z',
            band_ready_at: null,
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
            logic.actions.loadSeriesBands({})
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

    it('recharts the picked week', async () => {
        // The picker only moves this reducer, so a missing reload or a missing body field would
        // leave the default week on screen under the new label.
        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.setDateRange({ date_from: '-2wStart', date_to: '-2wEnd' })
        }).toFinishAllListeners()

        expect(logsAnomaliesSeriesBandsCreate).toHaveBeenCalledTimes(2)
        const [, body] = (logsAnomaliesSeriesBandsCreate as jest.Mock).mock.calls[1]
        expect(body).toMatchObject({
            serviceName: 'checkout',
            dateRange: { date_from: '-2wStart', date_to: '-2wEnd' },
        })
    })

    it('shows the backend reason a window was rejected', async () => {
        // Without this the banner reads "Non-OK response (status 400)", which leaves the user
        // no way to know their range was too wide.
        const rejection = new ApiError(undefined, 400, undefined, {
            error: 'The window may span at most 7 days.',
        })
        ;(logsAnomaliesSeriesBandsCreate as jest.Mock).mockRejectedValue(rejection)

        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
        }).toFinishAllListeners()

        expect(logic.values.seriesBandsError).toBe('The window may span at most 7 days.')
    })

    it('drops a slow response for a service the user has already left', async () => {
        // The charts carry no service name of their own, so a late response landing under the
        // new selection would be read as that service's volume.
        let finishFirst: (response: LogsSeriesBandsResponseApi) => void = () => {}
        ;(logsAnomaliesSeriesBandsCreate as jest.Mock)
            .mockReturnValueOnce(new Promise<LogsSeriesBandsResponseApi>((resolve) => (finishFirst = resolve)))
            .mockResolvedValueOnce(seriesBandsResponse(1))

        logic.actions.setServiceName('checkout')
        logic.actions.setServiceName('worker')
        finishFirst(seriesBandsResponse(9))
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.seriesBands?.series).toHaveLength(1)
    })

    it('sends a clicked bucket to the viewer as list filters', async () => {
        // A scalar `serviceNames` or `severityLevels` is re-split on commas by the viewer's
        // `parseTagsFilter`, so both have to arrive as lists.
        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
        }).toFinishAllListeners()

        await expectLogic(logic, () => {
            logic.actions.openLogsForBucket('error', {
                date_from: '2026-08-17T09:00:00Z',
                date_to: '2026-08-17T10:00:00Z',
            })
        }).toFinishAllListeners()

        expect(router.values.searchParams).toMatchObject({
            activeTab: 'viewer',
            serviceNames: ['checkout'],
            severityLevels: ['error'],
            dateRange: { date_from: '2026-08-17T09:00:00Z', date_to: '2026-08-17T10:00:00Z' },
        })
    })

    it('takes the service and the window off the URL', async () => {
        await expectLogic(logic, () => {
            router.actions.push('/logs', {
                activeTab: 'anomalies',
                anomaliesService: 'checkout',
                anomaliesDateRange: { date_from: '-24h' },
            })
        }).toFinishAllListeners()

        expect(logic.values.serviceName).toBe('checkout')
        expect(logic.values.dateRange).toEqual({ date_from: '-24h' })
        const [, body] = (logsAnomaliesSeriesBandsCreate as jest.Mock).mock.calls.at(-1)
        expect(body).toMatchObject({ serviceName: 'checkout', dateRange: { date_from: '-24h' } })
    })

    it('writes the picked service and window to the URL, and leaves the default window out', async () => {
        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
        }).toFinishAllListeners()

        expect(router.values.searchParams.anomaliesService).toBe('checkout')
        // A param for the default would ride along in every link minted from this tab.
        expect(router.values.searchParams).not.toHaveProperty('anomaliesDateRange')

        await expectLogic(logic, () => {
            logic.actions.setDateRange({ date_from: '-24h' })
        }).toFinishAllListeners()

        expect(router.values.searchParams.anomaliesDateRange).toEqual({ date_from: '-24h' })

        // Back to the default, and the param has to go with it.
        await expectLogic(logic, () => {
            logic.actions.setServiceName(null)
            logic.actions.setDateRange({ date_from: '-7d' })
        }).toFinishAllListeners()

        expect(router.values.searchParams).not.toHaveProperty('anomaliesService')
        expect(router.values.searchParams).not.toHaveProperty('anomaliesDateRange')
    })

    it('leaves the viewer tab own service and window params alone', async () => {
        // Both tabs live under the same URL, so sharing `serviceNames` or `dateRange` would let
        // one tab's picker rewrite the other tab's filters.
        await expectLogic(logic, () => {
            router.actions.push('/logs', {
                serviceNames: ['api'],
                dateRange: { date_from: '-1h' },
            })
        }).toFinishAllListeners()

        expect(logic.values.serviceName).toBeNull()
        expect(logic.values.dateRange).toEqual({ date_from: '-7d' })

        await expectLogic(logic, () => {
            logic.actions.setServiceName('checkout')
            logic.actions.setDateRange({ date_from: '-24h' })
        }).toFinishAllListeners()

        expect(router.values.searchParams.serviceNames).toEqual(['api'])
        expect(router.values.searchParams.dateRange).toEqual({ date_from: '-1h' })
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
