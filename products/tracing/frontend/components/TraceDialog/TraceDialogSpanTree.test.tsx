import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import type { Span } from 'products/tracing/frontend/types'

import { traceViewLogic } from '../TraceView/traceViewLogic'
import { TRACE_DIALOG_VIEW_ID, traceDialogLogic } from './traceDialogLogic'
import { TraceDialogSpanTree } from './TraceDialogSpanTree'

function span(spanId: string, parentSpanId: string): Span {
    return {
        uuid: spanId,
        trace_id: 'abc123',
        span_id: spanId,
        parent_span_id: parentSpanId,
        name: `${spanId} span`,
        kind: 0,
        service_name: 'agent-worker',
        status_code: 0,
        timestamp: '2026-10-14T10:00:00.000000Z',
        end_time: '2026-10-14T10:00:01.000000Z',
        duration_nano: 1_000_000_000,
        is_root_span: parentSpanId === '',
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
    }
}

describe('TraceDialogSpanTree', () => {
    beforeEach(() => {
        initKeaTests()
        // jsdom lays nothing out, so the virtualized list needs a size to render rows into.
        jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(600)
        jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1000)
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('renders a loaded trace and steps the selection with J', async () => {
        jest.spyOn(api.tracing, 'getTrace').mockResolvedValue({
            results: [span('ROOT', ''), span('A', 'ROOT'), span('B', 'ROOT')],
            hasMore: false,
            nextOffset: null,
        })
        const logic = traceDialogLogic()
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.openTraceDialog({ traceId: 'abc123', spanId: 'A' }, { entryPoint: 'log_details' })
        }).toDispatchActions(['loadTraceSpansSuccess'])

        const { container } = render(
            <Provider>
                <BindLogic logic={traceViewLogic} props={{ id: TRACE_DIALOG_VIEW_ID }}>
                    <TraceDialogSpanTree openedFrom={null} openedAtUs={null} />
                </BindLogic>
            </Provider>
        )
        logic.actions.selectNextSpan()

        await waitFor(() =>
            expect(container.querySelector('[data-attr="trace-dialog-span-row"][aria-pressed="true"]')).toHaveAttribute(
                'aria-label',
                'B span'
            )
        )
    })
})
