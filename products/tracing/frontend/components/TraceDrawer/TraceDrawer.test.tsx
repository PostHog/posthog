import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { tracingSpansTraceAiEventsRetrieve } from 'products/tracing/frontend/generated/api'

import { makeSpan } from '../../__mocks__/span'
import { EMPTY_TRACE_IDENTITY } from '../../traceIdentity'
import { TraceDrawer, type TraceDrawerProps } from './TraceDrawer'

jest.mock('products/tracing/frontend/generated/api', () => ({
    tracingSpansTraceAiEventsRetrieve: jest.fn(),
}))

const mockAiEventsRetrieve = tracingSpansTraceAiEventsRetrieve as jest.MockedFunction<
    typeof tracingSpansTraceAiEventsRetrieve
>

describe('TraceDrawer', () => {
    beforeEach(() => {
        initKeaTests()
        mockAiEventsRetrieve.mockReset()
        mockAiEventsRetrieve.mockResolvedValue({ results: [], has_more: false, limit: 500 })
    })
    afterEach(() => cleanup())

    const renderDrawer = (props: Partial<TraceDrawerProps>): void => {
        render(
            <Provider>
                <TraceDrawer
                    isOpen
                    traceId="abc123"
                    ts={null}
                    spans={[]}
                    identity={EMPTY_TRACE_IDENTITY}
                    sessionId={null}
                    showErrorsTab={false}
                    inspectorTab="attributes"
                    errorsScope={null}
                    onSelectInspectorTab={jest.fn()}
                    loading={false}
                    loadFailed={false}
                    selectedSpanId={null}
                    onSelectSpan={jest.fn()}
                    onClose={jest.fn()}
                    {...props}
                />
            </Provider>
        )
    }

    // A trace with no spans yet is still loading, so the notice must wait for the result.
    it.each([
        { loading: false, showsNotice: true },
        { loading: true, showsNotice: false },
    ])('with no spans and loading=$loading, shows the unavailable notice: $showsNotice', ({ loading, showsNotice }) => {
        renderDrawer({ loading })

        expect(screen.queryByText('Trace unavailable') !== null).toBe(showsNotice)
    })

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

    it('keeps the waterfall and shows a compact warning when a failed load still has spans', () => {
        const onRetry = jest.fn()
        renderDrawer({
            loading: false,
            loadFailed: true,
            onRetry,
            spans: [makeSpan({ trace_id: 'abc123', span_id: 'span-1', is_root_span: true })],
        })

        expect(screen.queryByText("Couldn't load trace")).toBeNull()
        expect(screen.queryByText("Couldn't load the full trace. Showing the spans loaded so far.")).not.toBeNull()
        expect(screen.getAllByText('GET /checkout').length).toBeGreaterThan(0)

        // LemonBanner renders its action twice (one per responsive breakpoint), both wired to the
        // same handler, so any one of them firing once is the behavior under test.
        screen.getAllByText('Try again')[0].click()
        expect(onRetry).toHaveBeenCalledTimes(1)
    })

    // The spans fetch and the AI events fetch resolve independently, so a spans result that is empty
    // must not read as "trace unavailable" while AI events for the same trace are still in flight.
    it('waits for AI events to finish loading before showing the unavailable notice', () => {
        mockAiEventsRetrieve.mockReturnValue(new Promise(() => {}))
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_AI_EVENTS]: true })

        renderDrawer({ loading: false })

        expect(screen.queryByText('Trace unavailable')).toBeNull()
    })
})
