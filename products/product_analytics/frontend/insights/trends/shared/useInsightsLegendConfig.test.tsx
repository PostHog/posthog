import { renderHook } from '@testing-library/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataNode, NodeKind, TrendsFilter, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import { useInsightsLegendConfig } from './useInsightsLegendConfig'

const insightProps: InsightLogicProps = { dashboardItemId: undefined }

const wrapper = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <BindLogic logic={insightLogic} props={insightProps}>
        {children}
    </BindLogic>
)

function setup({
    trendsFilter,
    flagEnabled = true,
}: { trendsFilter?: TrendsFilter; flagEnabled?: boolean } = {}): void {
    initKeaTests()
    featureFlagLogic.mount()
    featureFlagLogic.actions.setFeatureFlags([], {
        [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_LEGEND]: flagEnabled,
    })

    dataNodeLogic({ key: 'InsightViz.new', query: {} as DataNode }).mount()
    insightDataLogic(insightProps).mount()
    insightLogic(insightProps).mount()
    insightVizDataLogic(insightProps).mount()
    trendsDataLogic(insightProps).mount()
    const query: TrendsQuery = { kind: NodeKind.TrendsQuery, series: [], trendsFilter }
    insightVizDataLogic(insightProps).actions.updateQuerySource(query)
}

describe('useInsightsLegendConfig', () => {
    it('returns undefined when the quill legend flag is off', () => {
        setup({ flagEnabled: false, trendsFilter: { showLegend: true } })

        const { result } = renderHook(() => useInsightsLegendConfig({ insightProps }), { wrapper })

        expect(result.current).toBeUndefined()
    })

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
})
