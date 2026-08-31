import { fireEvent, render, screen } from '@testing-library/react'

import type { Span } from '../../types'
import { SpanMetricsTab } from './SpanMetricsTab'

// Capture the props the embedded TraceMetricSamples receives — the scope toggle's contract
// is which span filter (if any) reaches the samples component.
const capturedProps: { traceId: string; spanId?: string | null; dateFrom: string; dateTo: string }[] = []
jest.mock('products/metrics/frontend/components/TraceMetricSamples', () => ({
    TraceMetricSamples: (props: { traceId: string; spanId?: string | null; dateFrom: string; dateTo: string }) => {
        capturedProps.push(props)
        return null
    },
}))

const span = {
    trace_id: 'trace-abc',
    span_id: 'span-xyz',
    timestamp: '2026-06-11T08:00:00.000Z',
} as Span

describe('SpanMetricsTab', () => {
    beforeEach(() => {
        capturedProps.length = 0
    })

    it('defaults to whole-trace scope with a window around the span timestamp', () => {
        render(<SpanMetricsTab span={span} />)

        const props = capturedProps[capturedProps.length - 1]
        expect(props.traceId).toBe('trace-abc')
        expect(props.spanId).toBeNull()
        // ±1h around the span, same window the logs tab uses.
        expect(props.dateFrom).toBe('2026-06-11T07:00:00.000Z')
        expect(props.dateTo).toBe('2026-06-11T09:00:00.000Z')
    })

    it('narrows to the inspected span when the scope toggle flips', () => {
        render(<SpanMetricsTab span={span} />)

        // LemonSegmentedButton renders each option label more than once; any instance works.
        fireEvent.click(screen.getAllByText('This span')[0])

        const props = capturedProps[capturedProps.length - 1]
        expect(props.spanId).toBe('span-xyz')
    })
})
