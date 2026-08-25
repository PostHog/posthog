import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as api from '../generated/api'
import { featureFlagRequestUsageLogic } from './featureFlagRequestUsageLogic'

describe('featureFlagRequestUsageLogic', () => {
    let logic: ReturnType<typeof featureFlagRequestUsageLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/997/feature_flag_request_usage/': {
                    generated_at: '2026-08-21T00:00:00Z',
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
            generated_at: '2026-08-21T00:00:00Z',
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
            generated_at: '2026-08-21T00:00:00Z',
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

    it('fills empty hourly buckets with zero', async () => {
        logic.actions.setDates('2026-08-20T00:00:00Z', '2026-08-20T02:59:59Z')
        logic.actions.setInterval('hour')
        logic.actions.loadUsageResponseSuccess({
            generated_at: '2026-08-21T00:00:00Z',
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
            generated_at: '2026-08-21T00:00:00Z',
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
            generated_at: '2026-08-20T00:00:00Z',
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
            generated_at: '2026-08-21T00:00:00Z',
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
        const pythonSeriesId = logic.values.series.find(({ label }) => label.startsWith('posthog-python'))?.id

        logic.actions.setSelectedSDKs(['posthog-python'])

        expect(logic.values.series).toHaveLength(1)
        expect(logic.values.series[0].id).toBe(pythonSeriesId)
    })
})
