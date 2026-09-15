import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { MAX_RANGE_DAYS, csvCell, featureFlagRequestUsageLogic } from './featureFlagRequestUsageLogic'

describe('featureFlagRequestUsageLogic', () => {
    let logic: ReturnType<typeof featureFlagRequestUsageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/997/feature_flag_request_usage/': {
                    results: [],
                },
            },
        })
        initKeaTests()
        logic = featureFlagRequestUsageLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('builds chart series and SDK totals from remote and local usage', async () => {
        logic.actions.setDates('2026-08-20', '2026-08-20')
        logic.actions.loadUsageResponseSuccess({
            results: [
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'posthog-ruby',
                    request_count: 20,
                    billing_units: 20,
                },
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'local_evaluation',
                    sdk: 'posthog-ruby',
                    request_count: 3,
                    billing_units: 30,
                },
            ],
        })

        await expectLogic(logic).toMatchValues({
            totalBillingUnits: 50,
            sdkTotals: [
                {
                    sdk: 'posthog-ruby',
                    remoteRequests: 20,
                    localRequests: 3,
                    billingUnits: 50,
                    billingUnitsShare: 100,
                },
            ],
            series: [
                {
                    id: expect.any(Number),
                    label: 'posthog-ruby (remote)',
                    dates: ['2026-08-20T00:00:00.000Z'],
                    data: [20],
                },
                {
                    id: expect.any(Number),
                    label: 'posthog-ruby (local)',
                    dates: ['2026-08-20T00:00:00.000Z'],
                    data: [3],
                },
            ],
        })
    })

    it('applies SDK and request filters to metrics and shares', async () => {
        logic.actions.setDates('2026-08-20', '2026-08-20')
        logic.actions.loadUsageResponseSuccess({
            results: [
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'local_evaluation',
                    sdk: 'posthog-node',
                    request_count: 10,
                    billing_units: 100,
                },
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'posthog-python',
                    request_count: 100,
                    billing_units: 100,
                },
            ],
        })
        logic.actions.setSelectedSDKs(['posthog-node'])
        logic.actions.setRequestType('local_evaluation')
        logic.actions.setMetric('billing_units')

        await expectLogic(logic).toMatchValues({
            totalBillingUnits: 100,
            largestSdk: expect.objectContaining({ sdk: 'posthog-node', billingUnitsShare: 100 }),
            series: [
                {
                    id: expect.any(Number),
                    label: 'posthog-node (local)',
                    dates: ['2026-08-20T00:00:00.000Z'],
                    data: [100],
                },
            ],
        })
    })

    it('falls back to daily grouping when the selected range exceeds seven days', async () => {
        logic.actions.setDates('-24h', null)
        logic.actions.setInterval('hour')
        await expectLogic(logic).toMatchValues({ interval: 'hour', isHourlyAvailable: true })

        logic.actions.setDates('-30d', null)

        await expectLogic(logic).toMatchValues({ interval: 'day', isHourlyAvailable: false })
    })

    it('allows hourly grouping for the Last 7 days preset', async () => {
        logic.actions.setDates('-7d', null)

        await expectLogic(logic).toMatchValues({ isHourlyAvailable: true })
    })

    it.each([
        ['day' as const, '2026-08-01T00:00:00', '2026-09-01T00:00:00', MAX_RANGE_DAYS.day],
        ['hour' as const, '2026-08-01T00:00:00', '2026-08-09T00:00:00', MAX_RANGE_DAYS.hour],
    ])(
        'requests the longest allowed %s range without overshooting the limit',
        async (interval, dateFrom, dateTo, maximumDays) => {
            const listUsage = jest.spyOn(api, 'featureFlagRequestUsageList')
            logic.actions.setDates(dateFrom, dateTo)
            logic.actions.setInterval(interval)
            await expectLogic(logic).toFinishAllListeners()

            const params = listUsage.mock.calls.at(-1)?.[1]
            expect(logic.values.isRangeTooLong).toBe(false)
            expect(dayjs(params?.date_to).diff(dayjs(params?.date_from), 'day', true)).toEqual(maximumDays)
        }
    )

    it('skips the request when the selected range is longer than the API allows', async () => {
        await expectLogic(logic).toFinishAllListeners()

        await expectLogic(logic, () => logic.actions.setDates('2026-06-01', '2026-09-01'))
            .toDispatchActions(['setDates'])
            .toNotHaveDispatchedActions(['loadUsageResponse'])
            .toMatchValues({ isRangeTooLong: true })
    })

    it('fills empty hourly buckets with zero', async () => {
        logic.actions.setDates('2026-08-20T00:00:00Z', '2026-08-20T02:59:59Z')
        logic.actions.setInterval('hour')
        logic.actions.loadUsageResponseSuccess({
            results: [
                {
                    bucket: '2026-08-20T01:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'posthog-node',
                    request_count: 20,
                    billing_units: 20,
                },
            ],
        })

        await expectLogic(logic).toMatchValues({
            dates: ['2026-08-20T00:00:00.000Z', '2026-08-20T01:00:00.000Z', '2026-08-20T02:00:00.000Z'],
            series: [
                {
                    id: expect.any(Number),
                    label: 'posthog-node (remote)',
                    dates: ['2026-08-20T00:00:00.000Z', '2026-08-20T01:00:00.000Z', '2026-08-20T02:00:00.000Z'],
                    data: [0, 20, 0],
                },
            ],
        })
    })

    it('keeps the latest response when requests resolve out of order', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let resolveStale: (value: Awaited<ReturnType<typeof api.featureFlagRequestUsageList>>) => void = () => {}
        let resolveFresh: (value: Awaited<ReturnType<typeof api.featureFlagRequestUsageList>>) => void = () => {}
        jest.spyOn(api, 'featureFlagRequestUsageList')
            .mockImplementationOnce(() => new Promise((resolve) => (resolveStale = resolve)))
            .mockImplementationOnce(() => new Promise((resolve) => (resolveFresh = resolve)))

        logic.actions.loadUsageResponse()
        logic.actions.loadUsageResponse()
        resolveFresh({
            results: [
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'fresh-sdk',
                    request_count: 2,
                    billing_units: 2,
                },
            ],
        })
        await new Promise((resolve) => setTimeout(resolve, 0))
        expect(logic.values.usageResponse?.results[0].sdk).toBe('fresh-sdk')

        resolveStale({
            results: [
                {
                    bucket: '2026-08-19T00:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'stale-sdk',
                    request_count: 1,
                    billing_units: 1,
                },
            ],
        })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.usageResponse?.results[0].sdk).toBe('fresh-sdk')
    })

    it('keeps series IDs stable when filtering changes the visible series', async () => {
        logic.actions.setDates('2026-08-20', '2026-08-20')
        logic.actions.loadUsageResponseSuccess({
            results: [
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'posthog-node',
                    request_count: 20,
                    billing_units: 20,
                },
                {
                    bucket: '2026-08-20T00:00:00Z',
                    request_type: 'remote_evaluation',
                    sdk: 'posthog-python',
                    request_count: 10,
                    billing_units: 10,
                },
            ],
        })
        expect(new Set(logic.values.series.map(({ id }) => id)).size).toBe(2)
        const pythonSeriesId = logic.values.series.find(({ label }) => label.startsWith('posthog-python'))?.id

        logic.actions.setSelectedSDKs(['posthog-python'])

        expect(logic.values.series).toHaveLength(1)
        expect(logic.values.series[0].id).toBe(pythonSeriesId)
    })

    it('clears a load error when a new date range triggers a request', async () => {
        logic.actions.loadUsageResponseFailure('nope')
        expect(logic.values.loadError).toBe(true)

        logic.actions.setDates('-7d', null)

        await expectLogic(logic).toMatchValues({ loadError: false })
    })

    it.each(['=', '+', '-', '@', '\t', '\r'])('neutralizes a leading %p in CSV cells', (prefix) => {
        expect(csvCell(`${prefix}cmd(1)`)).toBe(`"'${prefix}cmd(1)"`)
    })
})
