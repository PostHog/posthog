jest.mock('~/queries/query', () => ({
    __esModule: true,
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn().mockResolvedValue({ result: [] }),
}))

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ChartOverlayState, adHocInsightProps, chartOverlayState, embeddedVisionChartQuery } from './VisionInsightChart'

const TRENDS_VIZ: InsightVizNode = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        series: [{ kind: NodeKind.EventsNode, event: '$recording_observed' }],
    } as TrendsQuery,
}

describe('VisionInsightChart', () => {
    describe('chartOverlayState', () => {
        // `insightData` is always a truthy object from the selector, so the decision must hinge on `result`, not the object.
        const cases: [string, { result?: unknown } | null | undefined, boolean, boolean, ChartOverlayState][] = [
            ['before the lazy renderer starts a query', { result: undefined }, false, false, 'loading'],
            ['null insightData while loading', null, true, true, 'loading'],
            ['null insightData settled (cancelled)', null, false, true, 'error'],
            ['truthy object with no result while loading', { result: undefined }, true, true, 'loading'],
            ['truthy object with no result settled', { result: undefined }, false, true, 'error'],
            ['loaded with rows', { result: [{ x: 1 }] }, false, true, 'none'],
            ['loaded but empty result', { result: [] }, false, true, 'none'],
            ['loaded, ignores a stale loading flag during refresh', { result: [{ x: 1 }] }, true, true, 'none'],
        ]

        it.each(cases)('%s', (_label, insightData, loading, queryStarted, expected) => {
            expect(chartOverlayState(insightData, loading, queryStarted)).toEqual(expected)
        })
    })

    describe('persons modal opt-out', () => {
        // hidePersonsModal only reaches the modal gate via `new-AdHoc.`-keyed props (insightDataLogic's propsQuery),
        // so this guards the exact wiring that once silently regressed to a live modal.
        it('showPersonsModal is false for the props the chart builds', async () => {
            initKeaTests()
            const props = adHocInsightProps(
                { dashboardItemId: 'new-replay-vision-test-chart' },
                embeddedVisionChartQuery(TRENDS_VIZ)
            )
            expect(props.dashboardItemId).toBe('new-AdHoc.new-replay-vision-test-chart')

            const dataLogic = insightDataLogic(props)
            dataLogic.mount()
            const logic = insightLogic(props)
            logic.mount()

            expect(dataLogic.values.query).toMatchObject({ hidePersonsModal: true })
            expect(logic.values.showPersonsModal).toBe(false)

            logic.unmount()
            dataLogic.unmount()
        })
    })
})
