import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { userHasAccess } from 'lib/utils/accessControlUtils'
import { insightsApi } from 'scenes/insights/utils/api'

import { initKeaTests } from '~/test/init'
import { AccessControlResourceType } from '~/types'

import { metricsAttributeValuesRetrieve, metricsNamesRetrieve } from 'products/metrics/frontend/generated/api'

import { metricOptionKey, metricsStarterDashboardLogic } from './metricsStarterDashboardLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsNamesRetrieve: jest.fn(),
    metricsAttributeValuesRetrieve: jest.fn(),
}))
jest.mock('lib/utils/accessControlUtils', () => ({
    ...jest.requireActual('lib/utils/accessControlUtils'),
    userHasAccess: jest.fn(),
}))
jest.mock('scenes/insights/utils/api', () => ({
    insightsApi: { create: jest.fn() },
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), warning: jest.fn(), error: jest.fn() },
}))

const mockNames = metricsNamesRetrieve as jest.MockedFunction<typeof metricsNamesRetrieve>
const mockValues = metricsAttributeValuesRetrieve as jest.MockedFunction<typeof metricsAttributeValuesRetrieve>
const mockInsightCreate = insightsApi.create as jest.MockedFunction<typeof insightsApi.create>
const mockUserHasAccess = userHasAccess as jest.MockedFunction<typeof userHasAccess>

describe('metricsStarterDashboardLogic', () => {
    let logic: ReturnType<typeof metricsStarterDashboardLogic.build>
    let apiCreateSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        mockNames.mockReset()
        mockValues.mockReset()
        mockInsightCreate.mockReset()
        mockUserHasAccess.mockReset().mockReturnValue(true)
        ;(lemonToast.success as jest.Mock).mockReset()
        ;(lemonToast.warning as jest.Mock).mockReset()
        ;(lemonToast.error as jest.Mock).mockReset()
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

    it('creates the dashboard, then one unaggregated insight per metric with the service filter', async () => {
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Billing service')
        logic.actions.setServiceName('billing-worker')
        logic.actions.setSelectedMetrics([
            metricOptionKey('billing.invoices.processed', 'sum'),
            metricOptionKey('billing.job.duration', 'histogram'),
        ])

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        expect(apiCreateSpy).toHaveBeenCalledTimes(1)
        expect(apiCreateSpy.mock.calls[0][1]).toEqual({ name: 'Billing service' })

        expect(mockInsightCreate).toHaveBeenCalledTimes(2)
        const [countInsight, histogramInsight] = mockInsightCreate.mock.calls.map(([insight]) => insight)
        expect(mockInsightCreate.mock.calls.map(([, dashboardIds]) => dashboardIds)).toEqual([[42], [42]])
        expect(countInsight.query).toMatchObject({
            kind: 'MetricsQuery',
            clauses: [
                {
                    name: 'a',
                    metricName: 'billing.invoices.processed',
                    metricType: 'sum',
                    filters: [{ key: 'service.name', op: 'eq', value: 'billing-worker' }],
                },
            ],
        })
        expect((countInsight.query as any).clauses[0]).not.toHaveProperty('aggregation')
        expect(histogramInsight.query).toMatchObject({
            clauses: [expect.objectContaining({ metricType: 'histogram' })],
        })
        expect((histogramInsight.query as any).clauses[0]).not.toHaveProperty('aggregation')
    })

    it('adds request rate, error rate and latency per service from span-derived series, even with no picked metrics', async () => {
        const derived = [
            { name: 'posthog.derived.spans.requests', metric_type: 'sum' },
            { name: 'posthog.derived.spans.errors', metric_type: 'sum' },
            { name: 'posthog.derived.spans.duration', metric_type: 'histogram' },
        ]
        // The picker list stops at its limit before the derived names, as for a team with many metrics.
        mockNames.mockImplementation(async (_team, params) =>
            params?.value === 'posthog.derived.spans.'
                ? { results: derived }
                : { results: [{ name: 'billing.queue.depth', metric_type: 'gauge' }] }
        )
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadServicePanelsAvailableSuccess'])
        logic.actions.setDashboardName('Checkout')
        logic.actions.setServiceName('checkout')

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        const insights = mockInsightCreate.mock.calls.map(([insight]) => insight)
        expect(insights.map((insight) => insight.name)).toEqual([
            'Request rate by service',
            'Error rate by service',
            'Latency p50 by service',
            'Latency p95 by service',
            'Latency p99 by service',
        ])
        const serviceScope = {
            groupBy: [{ key: 'service.name' }],
            filters: [{ key: 'service.name', op: 'eq', value: 'checkout' }],
        }
        const rate = { metricType: 'sum', aggregation: 'sum', rangeFunction: 'rate', ...serviceScope }
        expect(insights[1].query).toEqual({
            kind: 'MetricsQuery',
            clauses: [
                { name: 'a', metricName: 'posthog.derived.spans.errors', ...rate },
                { name: 'b', metricName: 'posthog.derived.spans.requests', ...rate },
            ],
            formula: 'a / b',
        })
        expect((insights[4].query as any).clauses).toEqual([
            {
                name: 'a',
                metricName: 'posthog.derived.spans.duration',
                metricType: 'histogram',
                aggregation: 'quantile',
                quantile: 0.99,
                ...serviceScope,
            },
        ])
    })

    it('leaves out the span-derived panels for a user without tracing access', async () => {
        mockUserHasAccess.mockImplementation((resource) => resource !== AccessControlResourceType.Tracing)
        mockNames.mockResolvedValue({
            results: [
                { name: 'billing.queue.depth', metric_type: 'gauge' },
                { name: 'posthog.derived.spans.requests', metric_type: 'sum' },
                { name: 'posthog.derived.spans.errors', metric_type: 'sum' },
                { name: 'posthog.derived.spans.duration', metric_type: 'histogram' },
            ],
        })
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadServicePanelsAvailableSuccess', 'loadMetricOptionsSuccess'])
        expect(logic.values.servicePanelsAvailable).toBe(false)

        logic.actions.setDashboardName('Billing')
        logic.actions.setSelectedMetrics([metricOptionKey('billing.queue.depth', 'gauge')])
        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        expect(mockInsightCreate.mock.calls.map(([insight]) => insight.name)).toEqual(['billing.queue.depth'])
    })

    it('navigates to the partially built dashboard when an insight create fails mid-loop', async () => {
        // The dashboard exists after a mid-loop failure — the flow must say so and go
        // there, not claim total failure and invite a duplicate-creating retry.
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Billing service')
        logic.actions.setSelectedMetrics([
            metricOptionKey('billing.invoices.processed', 'sum'),
            metricOptionKey('billing.job.duration', 'histogram'),
        ])
        mockInsightCreate
            .mockResolvedValueOnce({ id: 101, short_id: 'abc' } as any)
            .mockRejectedValueOnce(new Error('boom'))

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        expect(apiCreateSpy).toHaveBeenCalledTimes(1)
        expect(logic.values.isModalOpen).toBe(false)
        // Partial failure surfaces exactly one toast: the warning, not the success.
        expect(lemonToast.warning).toHaveBeenCalledTimes(1)
        expect((lemonToast.warning as jest.Mock).mock.calls[0][0]).toContain('only 1 of 2 insights')
        expect(lemonToast.success).not.toHaveBeenCalled()
    })

    it('keeps the picked type when the same metric name exists under two OTel types', async () => {
        mockNames.mockResolvedValue({
            results: [
                { name: 'billing.throughput', metric_type: 'sum' },
                { name: 'billing.throughput', metric_type: 'gauge' },
            ],
        })
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Billing service')
        logic.actions.setSelectedMetrics([metricOptionKey('billing.throughput', 'sum')])

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        // Name-keyed lookup would collapse to the last-listed type (gauge).
        const [insight] = mockInsightCreate.mock.calls[0]
        expect((insight.query as any).clauses[0]).toMatchObject({
            metricName: 'billing.throughput',
            metricType: 'sum',
        })
    })

    it('drops non-enum metric types instead of sending raw ingest strings', async () => {
        mockNames.mockResolvedValue({ results: [{ name: 'legacy.metric', metric_type: 'counter' }] })
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Legacy')
        logic.actions.setSelectedMetrics([metricOptionKey('legacy.metric', 'counter')])

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        const [insight] = mockInsightCreate.mock.calls[0]
        expect((insight.query as any).clauses[0].metricType).toBeUndefined()
    })

    it('guards against double submission while the create is in flight', async () => {
        logic.actions.openModal()
        await expectLogic(logic).toDispatchActions(['loadMetricOptionsSuccess'])
        logic.actions.setDashboardName('Billing service')
        logic.actions.setSelectedMetrics([metricOptionKey('billing.queue.depth', 'gauge')])

        await expectLogic(logic, () => {
            logic.actions.createDashboard()
            logic.actions.createDashboard()
        }).toDispatchActions(['createDashboardSuccess'])

        expect(apiCreateSpy).toHaveBeenCalledTimes(1)
    })
})
