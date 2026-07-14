import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { insightsApi } from 'scenes/insights/utils/api'

import { initKeaTests } from '~/test/init'

import { metricsAttributeValuesRetrieve, metricsValuesRetrieve } from 'products/metrics/frontend/generated/api'

import { metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsAttributeValuesRetrieve: jest.fn(),
}))
jest.mock('scenes/insights/utils/api', () => ({
    insightsApi: { create: jest.fn() },
}))

const mockNames = metricsValuesRetrieve as jest.MockedFunction<typeof metricsValuesRetrieve>
const mockValues = metricsAttributeValuesRetrieve as jest.MockedFunction<typeof metricsAttributeValuesRetrieve>
const mockInsightCreate = insightsApi.create as jest.MockedFunction<typeof insightsApi.create>

describe('metricsStarterDashboardLogic', () => {
    let logic: ReturnType<typeof metricsStarterDashboardLogic.build>
    let apiCreateSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        mockNames.mockReset()
        mockValues.mockReset()
        mockInsightCreate.mockReset()
        mockNames.mockResolvedValue({
            results: [
                { name: 'billing.invoices.processed', metric_type: 'sum' },
                { name: 'billing.queue.depth', metric_type: 'gauge' },
                { name: 'billing.job.duration', metric_type: 'histogram' },
            ],
        })
        mockValues.mockResolvedValue({
            results: [
                { id: 'billing-worker', name: 'billing-worker', count: 10 },
                { id: 'checkout', name: 'checkout', count: 5 },
            ],
        })
        mockInsightCreate.mockResolvedValue({ id: 101, short_id: 'abc' } as any)
        apiCreateSpy = jest.spyOn(api, 'create').mockResolvedValue({ id: 42, name: 'Billing' } as any)
        logic = metricsStarterDashboardLogic()
        logic.mount()
    })

    afterEach(() => {
        apiCreateSpy.mockRestore()
        logic?.unmount()
    })

    it('opening the modal loads the service and metric options', async () => {
        await expectLogic(logic, () => {
            logic.actions.openModal()
        }).toDispatchActions(['loadServicesSuccess', 'loadMetricOptionsSuccess'])

        expect(logic.values.services).toEqual(['billing-worker', 'checkout'])
        expect(logic.values.metricOptions).toHaveLength(3)
    })

    it('creates the dashboard, then one insight per metric with the recommended aggregation and service filter', async () => {
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Billing service')
        logic.actions.setServiceName('billing-worker')
        logic.actions.setSelectedMetrics(['billing.invoices.processed', 'billing.job.duration'])

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        expect(apiCreateSpy).toHaveBeenCalledTimes(1)
        expect(apiCreateSpy.mock.calls[0][1]).toEqual({ name: 'Billing service' })

        expect(mockInsightCreate).toHaveBeenCalledTimes(2)
        const [countInsight, histogramInsight] = mockInsightCreate.mock.calls.map(([insight]) => insight)
        expect(countInsight.dashboards).toEqual([42])
        expect(countInsight.query).toMatchObject({
            kind: 'MetricsQuery',
            clauses: [
                {
                    name: 'a',
                    metricName: 'billing.invoices.processed',
                    aggregation: 'increase', // recommended for counters
                    metricType: 'sum',
                    filters: [{ key: 'service.name', op: 'eq', value: 'billing-worker' }],
                },
            ],
        })
        expect(histogramInsight.query).toMatchObject({
            clauses: [expect.objectContaining({ aggregation: 'p95', metricType: 'histogram' })],
        })
    })

    it('guards against double submission while the create is in flight', async () => {
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Billing service')
        logic.actions.setSelectedMetrics(['billing.queue.depth'])

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        expect(apiCreateSpy).toHaveBeenCalledTimes(1)
    })
})
