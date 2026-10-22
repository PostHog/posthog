import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { tracingSpansTraceAiEventsRetrieve } from 'products/tracing/frontend/generated/api'

import { makeSpan } from '../../__mocks__/span'
import { EMPTY_TRACE_IDENTITY } from '../../traceIdentity'
import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TraceDrawer, type TraceDrawerProps } from './TraceDrawer'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansTraceAiEventsRetrieve: jest.fn(),
}))

const mockAiEventsRetrieve = tracingSpansTraceAiEventsRetrieve as jest.MockedFunction<
    typeof tracingSpansTraceAiEventsRetrieve
>

describe('TraceDrawer', () => {
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        mockAiEventsRetrieve.mockReset()
        mockAiEventsRetrieve.mockResolvedValue({ results: [], has_more: false, limit: 500 })
        captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })
    afterEach(() => {
        cleanup()
        captureSpy.mockRestore()
    })

    const renderDrawer = (props: Partial<TraceDrawerProps>): void => {
        const view = traceViewLogic({ id: 'trace-drawer-test' })
        view.mount()
        view.actions.showTrace(null, 'attributes')
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
