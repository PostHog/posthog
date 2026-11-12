import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { getChart, setupChartTests } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { tracingSpansTraceAiEventsRetrieve } from 'products/tracing/frontend/generated/api'

import { makeSpan } from '../../__mocks__/span'
import { compareRowKey } from '../../compareUtils'
import { EMPTY_TRACE_IDENTITY } from '../../traceIdentity'
import { tracingConfigLogic } from '../../tracingConfigLogic'
import type { Span, SpanInspectorTab } from '../../types'
import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TraceDrawer, type TraceDrawerProps } from './TraceDrawer'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansTraceAiEventsRetrieve: jest.fn(),
}))

jest.mock('products/metrics/frontend/components/TraceMetricSamples', () => ({
    TraceMetricSamples: () => null,
}))

const mockAiEventsRetrieve = tracingSpansTraceAiEventsRetrieve as jest.MockedFunction<
    typeof tracingSpansTraceAiEventsRetrieve
>

describe('TraceDrawer', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        // The view mode persists, so a mode that one test leaves would carry over into the next.
        localStorage.clear()
        initKeaTests()
        mockAiEventsRetrieve.mockReset()
        mockAiEventsRetrieve.mockResolvedValue({ results: [], has_more: false, limit: 500 })
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })
    afterEach(() => {
        cleanup()
        captureSpy.mockRestore()
    })

    const renderDrawer = (props: Partial<TraceDrawerProps>, tab: SpanInspectorTab = 'attributes'): void => {
        const view = traceViewLogic({ id: 'trace-drawer-test' })
        view.mount()
        view.actions.showTrace(null, tab)
        render(
            <Provider>
                <TraceDrawer
                    viewId="trace-drawer-test"
                    isOpen
                    traceId="abc123"
                    ts={null}
                    spans={[]}
                    identity={EMPTY_TRACE_IDENTITY}
                    sessionId={null}
                    showErrorsTab={false}
                    errorsScope={null}
                    inspectorOpen
                    onToggleInspector={jest.fn()}
                    isFullscreen={false}
                    onToggleFullscreen={jest.fn()}
                    loading={false}
                    loadFailed={false}
                    filtersActive={false}
                    onClose={jest.fn()}
                    {...props}
                />
            </Provider>
        )
    }

    const unavailableCaptures = (): unknown[][] =>
        captureSpy.mock.calls.filter(([event]) => event === 'tracing trace unavailable')

    // A trace with no spans yet is still loading, so the notice and its capture must wait for the result.
    // Without filters the notice must not blame them, since the trace dialog never has any.
    it.each([
        { loading: false, filtersActive: true, showsNotice: true },
        { loading: false, filtersActive: false, showsNotice: true },
        { loading: true, filtersActive: true, showsNotice: false },
    ])(
        'with no spans, loading=$loading and filtersActive=$filtersActive, shows the unavailable notice: $showsNotice',
        ({ loading, filtersActive, showsNotice }) => {
            renderDrawer({ loading, filtersActive })

            expect(screen.queryByText('Trace unavailable') !== null).toBe(showsNotice)
            if (showsNotice) {
                expect(screen.queryByText(/current filters/) !== null).toBe(filtersActive)
            }
            expect(unavailableCaptures()).toEqual(
                showsNotice ? [['tracing trace unavailable', { filters_active: filtersActive, surface: 'drawer' }]] : []
            )
        }
    )

    // A failed fetch must read as an error, not as "this trace has no spans" — the two share the
    // same empty `spans` array but mean opposite things to the user.
    it('shows a retryable error instead of the unavailable notice when the trace failed to load', () => {
        const onRetry = jest.fn()
        renderDrawer({ loading: false, loadFailed: true, onRetry })

        expect(screen.queryByText("Couldn't load trace")).not.toBeNull()
        expect(screen.queryByText('Trace unavailable')).toBeNull()

        screen.getByText('Try again').click()
        expect(onRetry).toHaveBeenCalledTimes(1)
    })

    it.each([
        { failedLoad: 'spans', loadFailed: true, aiEventsFail: false, spanRetries: 1, aiEventsFetches: 0 },
        { failedLoad: 'AI events', loadFailed: false, aiEventsFail: true, spanRetries: 0, aiEventsFetches: 2 },
    ])(
        'keeps the waterfall and shows a compact warning when the $failedLoad load fails but spans exist',
        async ({ loadFailed, aiEventsFail, spanRetries, aiEventsFetches }) => {
            if (aiEventsFail) {
                mockAiEventsRetrieve.mockRejectedValueOnce(new Error('boom'))
                featureFlagLogic.mount()
                featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_AI_EVENTS]: true })
            }
            const onRetry = jest.fn()
            renderDrawer({
                loading: false,
                loadFailed,
                onRetry,
                spans: [makeSpan({ trace_id: 'abc123', span_id: 'span-1', is_root_span: true })],
            })

            expect(
                await screen.findByText("Couldn't load the full trace. Showing the spans loaded so far.")
            ).toBeInTheDocument()
            expect(screen.queryByText("Couldn't load trace")).toBeNull()
            expect(screen.getAllByText('GET /checkout').length).toBeGreaterThan(0)

            // LemonBanner renders its action twice (one per responsive breakpoint), both wired to the
            // same handler, so any one of them firing once is the behavior under test.
            screen.getAllByText('Try again')[0].click()
            expect(onRetry).toHaveBeenCalledTimes(spanRetries)
            expect(mockAiEventsRetrieve).toHaveBeenCalledTimes(aiEventsFetches)
        }
    )

    // The spans fetch and the AI events fetch resolve independently, so a spans result that is empty
    // must not read as "trace unavailable" while AI events for the same trace are still in flight.
    it('waits for AI events to finish loading before showing the unavailable notice', () => {
        mockAiEventsRetrieve.mockReturnValue(new Promise(() => {}))
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_AI_EVENTS]: true })

        renderDrawer({ loading: false })

        expect(screen.queryByText('Trace unavailable')).toBeNull()
        expect(unavailableCaptures()).toEqual([])
    })

    // Fails when the view stops passing the trace's spans to the inspector: the Operations tab then
    // disappears and the inspector falls back to Attributes.
    it('shows the operations of the trace', () => {
        renderDrawer(
            {
                spans: [
                    makeSpan({ trace_id: 'abc123', span_id: 'span-1', is_root_span: true }),
                    makeSpan({
                        trace_id: 'abc123',
                        span_id: 'span-2',
                        parent_span_id: 'span-1',
                        is_root_span: false,
                        name: 'SELECT orders',
                    }),
                ],
            },
            'operations'
        )

        expect(screen.queryByText('Operations')).not.toBeNull()
        expect(screen.queryByText('2 operations · 2 spans')).not.toBeNull()
        expect(traceViewLogic({ id: 'trace-drawer-test' }).values.operationSpans).toHaveLength(2)
    })

    // Fails when the Metrics tab needs a gate other than the metrics product flag and metrics view access,
    // or when the tab shows without one of them.
    it.each([
        { metricsFlag: true, access: AccessControlLevel.Viewer, shows: true },
        { metricsFlag: false, access: AccessControlLevel.Viewer, shows: false },
        { metricsFlag: true, access: AccessControlLevel.None, shows: false },
    ])(
        'with the metrics flag on: $metricsFlag and metrics access: $access, shows the Metrics tab: $shows',
        ({ metricsFlag, access, shows }) => {
            featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: metricsFlag })
            window.POSTHOG_APP_CONTEXT = {
                ...window.POSTHOG_APP_CONTEXT,
                resource_access_control: {
                    ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                    [AccessControlResourceType.Metrics]: access,
                },
            } as AppContext
            renderDrawer({ spans: [makeSpan({ trace_id: 'abc123', span_id: 'span-1', is_root_span: true })] })

            const tabBar = within(
                document.querySelector('[data-attr="tracing-inspector-tabs"] [role="tablist"]') as HTMLElement
            )
            expect(tabBar.queryByText('Metrics') !== null).toBe(shows)
        }
    )

    // Fails when a click on the tab already on screen sends the tab event. The span has no query, so the chosen
    // Query tab falls back to Attributes, and a click on Attributes changes nothing the person sees. The click on
    // Raw keeps the first check from passing on a tab bar that sends nothing at all.
    it('sends the tab event only for a click that changes the tab on screen', () => {
        renderDrawer({ spans: [makeSpan({ trace_id: 'abc123', span_id: 'span-1', is_root_span: true })] }, 'query')
        const tabEvents = (): unknown[][] =>
            captureSpy.mock.calls.filter(([event]) => event === 'tracing trace inspector tab changed')
        // The tab content repeats some labels, so the clicks stay inside the tab bar.
        const tabBar = within(
            document.querySelector('[data-attr="tracing-inspector-tabs"] [role="tablist"]') as HTMLElement
        )

        tabBar.getByText('Attributes').click()
        expect(tabEvents()).toEqual([])

        tabBar.getByText('Raw').click()
        expect(tabEvents()).toEqual([['tracing trace inspector tab changed', { tab: 'raw', surface: 'drawer' }]])
    })

    describe('call tree', () => {
        const traceSpan = (span_id: string, parent_span_id: string, service_name: string, name: string): Span =>
            makeSpan({
                trace_id: 'abc123',
                uuid: span_id,
                span_id,
                parent_span_id,
                service_name,
                name,
                is_root_span: parent_span_id === '',
            })

        setupChartTests()
        // The flame graph's rows are 22px tall and the chart is 800px wide in jsdom.
        const flameRow = (depth: number): { clientX: number; clientY: number } => ({
            clientX: 400,
            clientY: depth * 22 + 11,
        })

        beforeEach(() => {
            // jsdom lays nothing out, so the virtualized span tree needs a size to render rows into.
            jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(600)
            jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1000)
        })
        afterEach(() => {
            jest.restoreAllMocks()
        })

        // Four bars: the third cache GET runs under a different caller, so it is not merged with the other two.
        it('switches the left pane to the call tree, and captures the change once', () => {
            renderDrawer({
                spans: [
                    traceSpan('span-1', '', 'checkout-api', 'POST /orders'),
                    traceSpan('span-2', 'span-1', 'postgres', 'SELECT orders'),
                    traceSpan('span-3', 'span-1', 'checkout-api', 'cache GET'),
                    traceSpan('span-4', 'span-1', 'checkout-api', 'cache GET'),
                    traceSpan('span-5', 'span-2', 'checkout-api', 'cache GET'),
                ],
            })
            const spanRow = (): Element | null => document.querySelector('[data-attr="trace-dialog-span-row"]')
            const callTreeOption = (): HTMLElement =>
                document.querySelector<HTMLElement>('[data-attr="tracing-trace-view-calltree"]')!
            expect(spanRow()).not.toBeNull()
            expect(() => getChart()).toThrow()

            fireEvent.click(callTreeOption())
            fireEvent.click(callTreeOption())

            expect(spanRow()).toBeNull()
            expect(getChart().canvas.getAttribute('aria-label')).toBe('Flame graph with 4 nodes')
            expect(captureSpy.mock.calls.filter(([event]) => event === 'tracing trace view changed')).toEqual([
                ['tracing trace view changed', { view: 'calltree', surface: 'drawer' }],
            ])
        })

        // Two services run GET /x, so a focus that matches on the name alone opens the wrong one.
        it('focuses the highlighted operation of its own service, keeps a drill when the highlight clears, and captures only clicked focus changes', () => {
            tracingConfigLogic.mount()
            tracingConfigLogic.actions.setTraceViewMode('calltree', 'drawer')
            renderDrawer({
                spans: [
                    traceSpan('span-1', '', 'checkout-api', 'POST /orders'),
                    traceSpan('span-2', 'span-1', 'web', 'GET /x'),
                    traceSpan('span-3', 'span-2', 'web', 'web-only'),
                    traceSpan('span-4', 'span-1', 'api', 'GET /x'),
                    traceSpan('span-5', 'span-4', 'api', 'api-only'),
                ],
            })

            act(() => {
                traceViewLogic({ id: 'trace-drawer-test' }).actions.highlightOperation(
                    compareRowKey({ service_name: 'api', name: 'GET /x' })
                )
            })

            const chart = getChart()
            expect(chart.flame.breadcrumb()).toEqual(['All', 'POST /orders', 'GET /x'])

            fireEvent.click(chart.element, flameRow(2))
            expect(chart.flame.breadcrumb()).toEqual(['All', 'POST /orders', 'GET /x', 'api-only'])
            act(() => {
                traceViewLogic({ id: 'trace-drawer-test' }).actions.setInspectorTab('logs')
            })
            expect(getChart().flame.breadcrumb()).toEqual(['All', 'POST /orders', 'GET /x', 'api-only'])
            fireEvent.click(getChart().flame.resetButton()!)

            expect(captureSpy.mock.calls.filter(([event]) => event === 'tracing trace call tree focused')).toEqual([
                ['tracing trace call tree focused', { direction: 'in', depth: 3, surface: 'drawer' }],
                ['tracing trace call tree focused', { direction: 'out', depth: 0, surface: 'drawer' }],
            ])
        })
    })

    it('shows a retryable error when the AI events fetch fails and there are no spans', async () => {
        mockAiEventsRetrieve.mockRejectedValueOnce(new Error('boom'))
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_AI_EVENTS]: true })
        const onRetry = jest.fn()

        renderDrawer({ loading: false, onRetry })

        expect(await screen.findByText("Couldn't load trace")).toBeInTheDocument()
        expect(screen.queryByText('Trace unavailable')).toBeNull()
        expect(unavailableCaptures()).toEqual([])

        screen.getByText('Try again').click()
        expect(mockAiEventsRetrieve).toHaveBeenCalledTimes(2)
        expect(onRetry).not.toHaveBeenCalled()
    })
})
