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
        // A settled query with no result is only an error when the load actually failed; without an error it has not been
        // dispatched yet (a first-render race), so it must stay a spinner rather than dead-end on the retry overlay.
        const cases: [string, { result?: unknown } | null | undefined, boolean, unknown, ChartOverlayState][] = [
            ['null insightData while loading', null, true, null, 'loading'],
            ['null insightData settled with no error (not dispatched yet)', null, false, null, 'loading'],
            ['null insightData settled after a failed load', null, false, { error: 'Failed to fetch' }, 'error'],
            ['truthy object with no result while loading', { result: undefined }, true, null, 'loading'],
            ['truthy object with no result settled, no error', { result: undefined }, false, null, 'loading'],
            [
                'truthy object with no result settled, failed load',
                { result: undefined },
                false,
                { detail: 'boom' },
                'error',
            ],
            ['loaded with rows', { result: [{ x: 1 }] }, false, null, 'none'],
            ['loaded but empty result', { result: [] }, false, null, 'none'],
            ['loaded, ignores a stale loading flag during refresh', { result: [{ x: 1 }] }, true, null, 'none'],
        ]

        it.each(cases)('%s', (_label, insightData, loading, error, expected) => {
            expect(chartOverlayState(insightData, loading, error)).toEqual(expected)
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
