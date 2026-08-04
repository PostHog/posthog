jest.mock('~/queries/query', () => ({
    __esModule: true,
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn().mockResolvedValue({ result: [] }),
}))

import { act, render, screen } from '@testing-library/react'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { performQuery } from '~/queries/query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { InsightLogicProps } from '~/types'

import {
    ChartOverlayState,
    VisionInsightChart,
    adHocInsightProps,
    chartOverlayState,
    embeddedVisionChartQuery,
} from './VisionInsightChart'

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
            ['null insightData while loading', null, true, false, 'loading'],
            ['null insightData settled (cancelled/never-loaded)', null, false, false, 'error'],
            ['truthy object with no result while loading', { result: undefined }, true, false, 'loading'],
            ['truthy object with no result settled', { result: undefined }, false, false, 'error'],
            ['loaded with rows', { result: [{ x: 1 }] }, false, false, 'none'],
            ['loaded but empty result', { result: [] }, false, false, 'none'],
            ['loaded, ignores a stale loading flag during refresh', { result: [{ x: 1 }] }, true, false, 'none'],
            // A query flagged as timed out is still loading in the background — surfacing that beats an opaque spinner.
            ['no result, still loading past the timeout threshold', { result: undefined }, true, true, 'timeout'],
            ['loaded with rows overrides a stale timeout flag', { result: [{ x: 1 }] }, false, true, 'none'],
        ]

        it.each(cases)('%s', (_label, insightData, loading, timedOut, expected) => {
            expect(chartOverlayState(insightData, loading, timedOut)).toEqual(expected)
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

    describe('timeout overlay', () => {
        // Guards the actual regression: a query flagged as timed out used to render an opaque spinner over
        // InsightVizDisplay's own InsightTimeoutState, leaving the user with no indication anything was wrong.
        it('shows a timeout message with a retry action instead of an endless spinner', async () => {
            initKeaTests()
            // Never resolves during the test, so the chart stays in a genuine "still loading" state throughout.
            jest.mocked(performQuery).mockReturnValue(new Promise(() => {}))

            const insightProps: InsightLogicProps = { dashboardItemId: 'new-vision-timeout-test' }
            const chartProps = adHocInsightProps(insightProps, embeddedVisionChartQuery(TRENDS_VIZ))
            const dataLogic = insightVizDataLogic(chartProps)
            dataLogic.mount()

            render(<VisionInsightChart query={TRENDS_VIZ} insightProps={insightProps} />)

            // Simulates the breakpoint in insightVizDataLogic's `loadData` listener firing after its
            // real-world delay, without waiting on that delay in the test.
            act(() => {
                dataLogic.actions.setTimedOutQueryId('test-query-id')
            })

            expect(await screen.findByText('This query is taking longer than usual.')).toBeTruthy()
            expect(screen.getByText('Retry')).toBeTruthy()
            expect(screen.queryByText("Couldn't load this chart.")).toBeNull()

            dataLogic.unmount()
        })
    })
})
