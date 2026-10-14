import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { makeSpan } from '../../__mocks__/span'
import { EMPTY_TRACE_IDENTITY } from '../../traceIdentity'
import { TraceDrawer, type TraceDrawerProps } from './TraceDrawer'

describe('TraceDrawer', () => {
    beforeEach(() => initKeaTests())
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
        expect(screen.queryByText("Couldn't refresh this trace. Showing the spans already loaded.")).not.toBeNull()
        expect(screen.getAllByText('GET /checkout').length).toBeGreaterThan(0)

        // LemonBanner renders its action twice (one per responsive breakpoint), both wired to the
        // same handler, so any one of them firing once is the behavior under test.
        screen.getAllByText('Try again')[0].click()
        expect(onRetry).toHaveBeenCalledTimes(1)
    })
})
