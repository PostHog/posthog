import { renderHook, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { getTrendResultCustomizationKey } from 'scenes/insights/utils'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    CompareFilter,
    DataNode,
    NodeKind,
    ResultCustomizationBy,
    TrendsFilter,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightModel } from '~/types'

import { useInsightsLegendConfig } from './useInsightsLegendConfig'

const insightProps: InsightLogicProps = { dashboardItemId: undefined }

const wrapper = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <BindLogic logic={insightLogic} props={insightProps}>
        {children}
    </BindLogic>
)

function setup({
    trendsFilter,
    compareFilter,
    results,
}: { trendsFilter?: TrendsFilter; compareFilter?: CompareFilter; results?: InsightModel['result'] } = {}): void {
    initKeaTests()
    featureFlagLogic.mount()

    const builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
    builtDataNodeLogic.mount()
    insightDataLogic(insightProps).mount()
    insightLogic(insightProps).mount()
    insightVizDataLogic(insightProps).mount()
    trendsDataLogic(insightProps).mount()
    const query: TrendsQuery = { kind: NodeKind.TrendsQuery, series: [], trendsFilter, compareFilter }
    insightVizDataLogic(insightProps).actions.updateQuerySource(query)
    builtDataNodeLogic.actions.loadDataSuccess({ result: results ?? [] })
}

const SERIES: InsightModel['result'] = [
    {
        action: { id: '$pageview', type: 'events', order: 0, name: '$pageview' },
        label: '$pageview',
        data: [1],
        days: [],
    },
    {
        action: { id: '$autocapture', type: 'events', order: 1, name: '$autocapture' },
        label: '$autocapture',
        data: [2],
        days: [],
    },
]

describe('useInsightsLegendConfig', () => {
    it.each([
        { legendPosition: 'left', expected: 'left' },
        { legendPosition: 'right', expected: 'right' },
        { legendPosition: undefined, expected: 'right' },
    ] as const)('maps legendPosition $legendPosition to position $expected', ({ legendPosition, expected }) => {
        setup({ trendsFilter: { showLegend: true, legendPosition } })

        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps }), { wrapper })

        expect(result.current?.position).toBe(expected)
    })

    it.each([
        { showLegend: true, expectedShow: true },
        { showLegend: undefined, expectedShow: false },
    ])('show is $expectedShow when trendsFilter.showLegend is $showLegend', ({ showLegend, expectedShow }) => {
        setup({ trendsFilter: { showLegend } })

        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps }), { wrapper })

        expect(result.current?.show).toBe(expectedShow)
    })

    it('persists an isolate through onSetHiddenSeries, so a legend click reaches the query', async () => {
        setup({ trendsFilter: { showLegend: true }, results: SERIES })
        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps }), { wrapper })
        const logic = trendsDataLogic(insightProps)
        const [first, second] = logic.values.indexedResults

        result.current.onSetHiddenSeries!([String(second.id)])

        await waitFor(() => {
            const { getTrendsHidden } = logic.values
            expect([getTrendsHidden(first), getTrendsHidden(second)]).toEqual([false, true])
        })
    })

    it('groups a compared series two rows onto one visibility key', () => {
        const [pageview] = SERIES
        setup({
            trendsFilter: { showLegend: true },
            compareFilter: { compare: true },
            results: [
                { ...pageview, compare: true, compare_label: 'current' },
                { ...pageview, compare: true, compare_label: 'previous' },
            ],
        })
        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps }), { wrapper })
        const [current, previous] = trendsDataLogic(insightProps).values.indexedResults

        const groupOf = result.current.visibilityGroupKey!

        expect(groupOf(String(current.id))).toBe(groupOf(String(previous.id)))
        expect(groupOf(String(current.id))).toBe(getTrendResultCustomizationKey(ResultCustomizationBy.Value, current))
    })

    it.each([
        { inSharedMode: false, expectedInteractive: true },
        { inSharedMode: true, expectedInteractive: false },
    ])(
        'interactive is $expectedInteractive when inSharedMode is $inSharedMode',
        ({ inSharedMode, expectedInteractive }) => {
            setup({ trendsFilter: { showLegend: true } })

            const { result } = renderHook(() => useInsightsLegendConfig({ insightProps, inSharedMode }), { wrapper })

            expect(result.current?.interactive).toBe(expectedInteractive)
        }
    )
})
