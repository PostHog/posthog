import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { PREFETCH_SPANS, tracingDataLogic } from './tracingDataLogic'
import { tracingViewerLogic } from './tracingViewerLogic'
import type { Span } from './types'

const createMockSpan = (uuid: string, traceId: string): Span => ({
    uuid,
    trace_id: traceId,
    span_id: uuid,
    parent_span_id: '',
    name: 'op',
    kind: 1,
    service_name: 'svc',
    status_code: 1,
    timestamp: '2024-01-01T00:00:00Z',
    end_time: '2024-01-01T00:00:00Z',
    duration_nano: 1000,
    is_root_span: true,
    matched_filter: true,
    attributes: {},
    resource_attributes: {},
})

describe('tracingViewerLogic', () => {
    let logic: ReturnType<typeof tracingViewerLogic.build>
    let getTraceSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        getTraceSpy = jest
            .spyOn(api.tracing, 'getTrace')
            .mockResolvedValue({ results: [], hasMore: false, nextOffset: null })
        logic = tracingViewerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        getTraceSpy.mockRestore()
    })

    // The prefetch decision drives whether opening a trace refetches it by id: a partial
    // prefetch batch is the trace's complete span set (no fetch), while a cold link (zero
    // loaded spans) or a possibly-truncated full batch must fetch. Getting this wrong either
    // refetches every drawer open or shows truncated waterfalls on cold links.
    it.each([
        ['no loaded spans (cold link)', 0, true],
        ['a partial prefetch batch', 2, false],
        ['a possibly-truncated full batch', PREFETCH_SPANS, true],
    ])('openTrace with %s %s', (_name, spanCount, shouldFetch) => {
        const spans = Array.from({ length: spanCount }, (_, i) => createMockSpan(`span-${i}`, 'trace-x'))
        tracingDataLogic().actions.fetchSpansSuccess(spans)

        logic.actions.openTrace('trace-x', { ts: '2024-01-01T00:00:00Z' })

        expect(logic.values.selectedTraceId).toBe('trace-x')
        expect(getTraceSpy.mock.calls.length > 0).toBe(shouldFetch)
    })
})
