import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { compareRowKey } from 'products/tracing/frontend/compareUtils'
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
        delete (Element.prototype as Partial<Element>).scrollTo
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

    // Fails when the highlight dims by the wrong key, or dims a folded chain that hides a span of the
    // operation, which would tell the person the operation is not in there.
    it('dims the rows outside the highlighted operation', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_OPERATIONS_TAB]: true })
        const view = traceViewLogic({ id: 'span-tree-test' })
        view.mount()
        view.actions.showTrace(null, 'operations')
        // ROOT > A, B and B > C > D > E > F, where A and D are the operation and C to E fold into a chain.
        view.actions.setSpans([
            span('ROOT', ''),
            { ...span('A', 'ROOT'), name: 'cache GET' },
            span('B', 'ROOT'),
            span('C', 'B'),
            { ...span('D', 'C'), name: 'cache GET' },
            span('E', 'D'),
            span('F', 'E'),
        ])
        view.actions.highlightOperation(compareRowKey({ service_name: 'agent-worker', name: 'cache GET' }))

        render(
            <Provider>
                <BindLogic logic={traceViewLogic} props={{ id: 'span-tree-test' }}>
                    <TraceDialogSpanTree openedFrom={null} openedAtUs={null} />
                </BindLogic>
            </Provider>
        )

        await screen.findByText('cache GET')
        const isDimmed = (name: string): boolean => screen.getByText(name).classList.contains('opacity-40')
        expect(isDimmed('cache GET')).toBe(false)
        expect(isDimmed('C span › … › E span')).toBe(false)
        expect([isDimmed('ROOT span'), isDimmed('B span'), isDimmed('F span')]).toEqual([true, true, true])
    })

    // Fails when the page of spans that the scroll to the operation loads pulls the list back to the selected
    // span, which leaves the highlighted spans off screen.
    it('keeps the highlighted operation in view when another page of spans loads', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_OPERATIONS_TAB]: true })
        const view = traceViewLogic({ id: 'span-tree-page-test' })
        view.mount()
        view.actions.showTrace(null, 'operations')
        // ROOT > P0 to P9 > five spans each: 61 rows, more than the list shows. The last row is the operation.
        const spans = [span('ROOT', ''), ...Array.from({ length: 10 }, (_, i) => span(`P${i}`, 'ROOT'))]
        for (let i = 0; i < 10; i++) {
            spans.push(...Array.from({ length: 5 }, (_, j) => span(`Q${i}-${j}`, `P${i}`)))
        }
        spans[spans.length - 1] = { ...spans[spans.length - 1], name: 'cache GET' }
        view.actions.setSpans(spans)
        // jsdom does not scroll, so a scroll sets the offset the list reads and fires the event it listens for.
        Element.prototype.scrollTo = function (this: Element, options?: ScrollToOptions | number) {
            this.scrollTop = typeof options === 'object' ? (options.top ?? 0) : 0
            this.dispatchEvent(new Event('scroll'))
        }
        const onLoadMore = jest.fn()
        render(
            <Provider>
                <BindLogic logic={traceViewLogic} props={{ id: 'span-tree-page-test' }}>
                    <TraceDialogSpanTree openedFrom={null} openedAtUs={null} hasMore onLoadMore={onLoadMore} />
                </BindLogic>
            </Provider>
        )
        await screen.findByText('ROOT span')

        act(() => view.actions.highlightOperation(compareRowKey({ service_name: 'agent-worker', name: 'cache GET' })))
        await screen.findByText('cache GET')
        expect(onLoadMore).toHaveBeenCalled()
        act(() => view.actions.setSpans([...spans, span('LATE', 'P9')]))

        expect(screen.getByText('cache GET')).toBeInTheDocument()
    })
})
