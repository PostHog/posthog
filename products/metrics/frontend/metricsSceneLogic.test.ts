import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import {
    AccessControlLevel,
    AccessControlResourceType,
    AppContext,
    FilterLogicalOperator,
    PropertyFilterType,
    PropertyOperator,
    UniversalFiltersGroup,
} from '~/types'

import { metricsQueryCreate, metricsValuesRetrieve } from 'products/metrics/frontend/generated/api'

import { metricsSceneLogic } from './metricsSceneLogic'

jest.mock('products/metrics/frontend/generated/api', () => ({
    ...jest.requireActual('products/metrics/frontend/generated/api'),
    metricsValuesRetrieve: jest.fn(),
    metricsQueryCreate: jest.fn(),
}))

const PICKER_ITEMS = [
    { name: 'requests_total', metric_type: 'sum' },
    { name: 'queue_depth', metric_type: 'gauge' },
]

const FILTER_GROUP: UniversalFiltersGroup = {
    type: FilterLogicalOperator.And,
    values: [
        {
            type: FilterLogicalOperator.And,
            values: [
                {
                    type: PropertyFilterType.MetricAttribute,
                    key: 'service_name',
                    value: ['api'],
                    operator: PropertyOperator.Exact,
                },
            ],
        },
    ],
}

describe('metricsSceneLogic', () => {
    let logic: ReturnType<typeof metricsSceneLogic.build>

    beforeEach(async () => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
        jest.mocked(metricsValuesRetrieve).mockResolvedValue({ results: PICKER_ITEMS })
        jest.mocked(metricsQueryCreate).mockReset().mockResolvedValue({ results: [] })
        logic = metricsSceneLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    describe('URL parameter parsing', () => {
        it('restores the viewer query state from URL params', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/metrics', {
                    activeTab: 'viewer',
                    metricName: 'queue_depth',
                    metricType: 'gauge',
                    aggregation: 'p95',
                    dateFrom: '-24h',
                    dateTo: '2026-08-25T00:00:00.000Z',
                    groupBy: '["service_name","env"]',
                    filterGroup: JSON.stringify(FILTER_GROUP),
                })
            }).toFinishAllListeners()

            expect(logic.values.activeTab).toEqual('viewer')
            expect(logic.values.metricName).toEqual('queue_depth')
            expect(logic.values.selectedMetricType).toEqual('gauge')
            // The shared link's own aggregation survives the recommendation cascade that
            // picking queue_depth (a gauge, recommending 'avg') triggers.
            expect(logic.values.aggregation).toEqual('p95')
            expect(logic.values.dateFrom).toEqual('-24h')
            expect(logic.values.dateTo).toEqual('2026-08-25T00:00:00.000Z')
            expect(logic.values.groupByKeys).toEqual(['service_name', 'env'])
            expect(logic.values.filterGroup).toEqual(FILTER_GROUP)
            // Applying the params dispatches setters whose own URL sync must not rewrite the
            // URL from half-applied state — the params stay in the address bar for a refresh.
            expect(router.values.searchParams).toMatchObject({ metricName: 'queue_depth', aggregation: 'p95' })
        })

        it('keeps the recommended aggregation for a link that has a metric but no aggregation param', async () => {
            await expectLogic(logic, () => {
                router.actions.push('/metrics', { metricName: 'queue_depth' })
            }).toFinishAllListeners()

            expect(logic.values.aggregation).toEqual('avg')
        })

        it.each([
            ['activeTab', 'nonsense', 'activeTab', 'overview'],
            ['aggregation', 'not-an-aggregation', 'aggregation', 'sum'],
            ['metricType', 'not-a-type', 'selectedMetricType', null],
        ])('falls back to the default for an invalid %s param', async (param, urlValue, valueKey, expected) => {
            await expectLogic(logic, () => {
                router.actions.push('/metrics', { [param]: urlValue })
            }).toFinishAllListeners()

            expect(logic.values[valueKey as keyof typeof logic.values]).toEqual(expected)
        })

        it.each([
            ['unparsable JSON', '{not valid json'],
            // kea-router pre-parses JSON-looking params, so these arrive as real values
            // and would crash the filter selectors without shape validation.
            ['a JSON array', '[1,2]'],
            ['a JSON object of the wrong shape', '{"a":1}'],
            ['a group with junk inside values', '{"type":"AND","values":[1]}'],
            // The viewer renders values[0] as a nested group, so a flat group (leaf chips
            // at the top level) would crash the filter bar.
            [
                'a flat group with a leaf at the top level',
                '{"type":"AND","values":[{"type":"metric_attribute","key":"service_name","value":["api"],"operator":"exact"}]}',
            ],
        ])('ignores a malformed filterGroup in the URL (%s)', async (_, urlValue) => {
            const before = logic.values.filterGroup
            await expectLogic(logic, () => {
                router.actions.push('/metrics', { filterGroup: urlValue })
            }).toFinishAllListeners()

            expect(logic.values.filterGroup).toEqual(before)
        })
    })

    describe('URL writing', () => {
        beforeEach(async () => {
            await expectLogic(logic, () => {
                router.actions.push('/metrics')
            }).toFinishAllListeners()
        })

        it('writes viewer state to the URL and drops params back at their defaults', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMetricName('requests_total')
                logic.actions.setDateFrom('-7d')
            }).toFinishAllListeners()

            // aggregation is written even when recommended ('increase' for this counter), so
            // restoring the link never has to re-derive it.
            expect(router.values.searchParams).toMatchObject({
                metricName: 'requests_total',
                aggregation: 'increase',
                dateFrom: '-7d',
            })

            await expectLogic(logic, () => {
                logic.actions.setDateFrom('-1h')
            }).toFinishAllListeners()

            expect(router.values.searchParams).not.toHaveProperty('dateFrom')
            expect(router.values.searchParams).toMatchObject({ metricName: 'requests_total' })
        })

        it('keeps viewer params in the URL when switching tabs', async () => {
            await expectLogic(logic, () => {
                logic.actions.setMetricName('requests_total')
                logic.actions.setActiveTab('sql')
            }).toFinishAllListeners()

            expect(router.values.searchParams).toMatchObject({ metricName: 'requests_total', activeTab: 'sql' })
        })

        it('does not write metrics params onto another scene URL', async () => {
            // An async cascade (e.g. the picker's late metric-type backfill) can fire after
            // the router already left /metrics while the scene logic is still mounted.
            await expectLogic(logic, () => {
                router.actions.push('/logs')
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.setMetricName('requests_total')
            }).toFinishAllListeners()

            expect(router.values.location.pathname).toContain('/logs')
            expect(router.values.searchParams).not.toHaveProperty('metricName')
        })
    })
})
