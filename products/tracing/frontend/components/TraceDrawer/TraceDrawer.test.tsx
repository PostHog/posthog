import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

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
})
