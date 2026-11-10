import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import type { Span } from 'products/tracing/frontend/types'

import { traceViewLogic } from '../TraceView/traceViewLogic'
import { traceEmbedLogic } from './traceEmbedLogic'

function span(spanId: string): Span {
    return {
        uuid: spanId,
        trace_id: 'abc123',
        span_id: spanId,
        parent_span_id: '',
        name: spanId,
        kind: 0,
        service_name: 'checkout',
        status_code: 0,
        timestamp: '2026-10-14T10:00:00.000000Z',
        end_time: '2026-10-14T10:00:01.000000Z',
        duration_nano: 1_000_000_000,
        is_root_span: false,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
    }
}

describe('traceEmbedLogic', () => {
    const props = {
        viewId: 'exception-e1',
        trace: { traceId: 'abc123', spanId: 'b1' },
        surface: 'exception_card' as const,
    }
    let getTraceSpy: jest.SpyInstance
    let captureSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        captureSpy = jest.spyOn(posthog, 'capture')
        getTraceSpy = jest.spyOn(api.tracing, 'getTrace')
    })

    afterEach(() => {
        getTraceSpy.mockRestore()
        captureSpy.mockRestore()
    })

    it('hands the loaded spans to its view, selects the linked span, and reports the load with its surface', async () => {
        getTraceSpy.mockResolvedValueOnce({ results: [span('A1'), span('B1')], hasMore: false, nextOffset: null })
        const logic = traceEmbedLogic(props)

        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadTraceSpansSuccess'])

        expect(traceViewLogic({ id: props.viewId }).values.selectedSpan?.span_id).toBe('B1')
        expect(captureSpy).toHaveBeenCalledWith(
            'tracing trace embed loaded',
            expect.objectContaining({ surface: 'exception_card', span_count: 2, truncated: false })
        )

        logic.unmount()
        expect(captureSpy).toHaveBeenCalledWith(
            'tracing trace embed closed',
            expect.objectContaining({ surface: 'exception_card' })
        )
    })

    it('marks a failed load so the tab offers a retry, and reports the failure with its surface', async () => {
        getTraceSpy.mockRejectedValueOnce(new Error('boom'))
        const logic = traceEmbedLogic(props)

        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadTraceSpansFailure'])
            .toMatchValues({ traceSpansFailed: true })
        expect(captureSpy).toHaveBeenCalledWith('tracing trace embed load failed', { surface: 'exception_card' })

        getTraceSpy.mockResolvedValueOnce({ results: [span('A1')], hasMore: false, nextOffset: null })
        await expectLogic(logic, () => logic.actions.loadTraceSpans())
            .toDispatchActions(['loadTraceSpansSuccess'])
            .toMatchValues({ traceSpansFailed: false })
        logic.unmount()
    })
})
