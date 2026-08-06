import { renderHook } from '@testing-library/react'
import { BindLogic } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendPieResult } from 'scenes/trends/__mocks__/trendsDataLogicMocks'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, TrendsFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps, InsightModel, TrendAPIResponse } from '~/types'

import { useInsightsLegendConfig } from './useInsightsLegendConfig'

const insightProps: InsightLogicProps = { dashboardItemId: undefined }

const wrapper = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <BindLogic logic={insightLogic} props={insightProps}>
        {children}
    </BindLogic>
)

function setup({
    trendsFilter,
    result,
}: { trendsFilter?: TrendsFilter; result?: TrendAPIResponse['result'] } = {}): void {
    initKeaTests()
    featureFlagLogic.mount()

    const builtDataNodeLogic = dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode })
    builtDataNodeLogic.mount()
    insightDataLogic(insightProps).mount()
    insightLogic(insightProps).mount()
    insightVizDataLogic(insightProps).mount()
    trendsDataLogic(insightProps).mount()
    const query: TrendsQuery = { kind: NodeKind.TrendsQuery, series: [], trendsFilter }
    insightVizDataLogic(insightProps).actions.updateQuerySource(query)
    if (result) {
        const insight: Partial<InsightModel> = { result }
        builtDataNodeLogic.actions.loadDataSuccess(insight)
    }
}

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

    it('onIsolateSeries dispatches toggleOtherSeriesHidden for the double-clicked series', async () => {
        setup({ trendsFilter: { showLegend: true }, result: trendPieResult.result })

        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps }), { wrapper })
        const logic = trendsDataLogic(insightProps)
        const firstSeries = logic.values.indexedResults[0]

        await expectLogic(logic, () => {
            result.current.onIsolateSeries!(String(firstSeries.id))
        }).toDispatchActions(['toggleOtherSeriesHidden'])
    })

    it.each([
        { name: 'fewer than two series', result: undefined, inSharedMode: false },
        { name: 'shared mode', result: trendPieResult.result, inSharedMode: true },
    ])('onIsolateSeries is undefined with $name', ({ result: insightResult, inSharedMode }) => {
        setup({ trendsFilter: { showLegend: true }, result: insightResult })

        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps, inSharedMode }), { wrapper })

        expect(result.current.onIsolateSeries).toBeUndefined()
    })
})
