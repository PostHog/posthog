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

// Capture the props the service-metrics pivot receives — the tab must hand the service
// metrics button the span's own service and the trace's time window.
const capturedMetricsButtonProps: {
    serviceName?: string | null
    dateFrom?: string | null
    dateTo?: string | null
}[] = []
jest.mock('products/metrics/frontend/components/ViewServiceMetricsButton', () => ({
    ViewServiceMetricsButton: (props: {
        serviceName?: string | null
        dateFrom?: string | null
        dateTo?: string | null
    }) => {
        capturedMetricsButtonProps.push(props)
        return null
    },
}))

const span = {
    trace_id: 'trace-abc',
    span_id: 'span-xyz',
    service_name: 'billing-worker',
    timestamp: '2026-06-11T08:00:00.000Z',
} as Span

describe('SpanMetricsTab', () => {
    beforeEach(() => {
        capturedProps.length = 0
        capturedMetricsButtonProps.length = 0
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

    it('offers a pivot to the span service metrics over the trace window', () => {
        render(<SpanMetricsTab span={span} />)

        const button = capturedMetricsButtonProps[capturedMetricsButtonProps.length - 1]
        expect(button.serviceName).toBe('billing-worker')
        // Same ±1h window the samples query uses, so the chart and the samples agree.
        expect(button.dateFrom).toBe('2026-06-11T07:00:00.000Z')
        expect(button.dateTo).toBe('2026-06-11T09:00:00.000Z')
    })
})
