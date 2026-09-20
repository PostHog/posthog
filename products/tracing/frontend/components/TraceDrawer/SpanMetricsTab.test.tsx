import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

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
    service_name: 'billing-worker',
    timestamp: '2026-06-11T08:00:00.000Z',
} as Span

describe('SpanMetricsTab', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        // Enable both gates on ViewServiceMetricsButton so the real component renders its link.
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.METRICS]: true })
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Metrics]: AccessControlLevel.Viewer,
            },
        } as AppContext
        capturedProps.length = 0
    })

    it('defaults to whole-trace scope with a window around the span timestamp', () => {
        render(
            <Provider>
                <SpanMetricsTab span={span} />
            </Provider>
        )

        const props = capturedProps[capturedProps.length - 1]
        expect(props.traceId).toBe('trace-abc')
        expect(props.spanId).toBeNull()
        // ±1h around the span, same window the logs tab uses.
        expect(props.dateFrom).toBe('2026-06-11T07:00:00.000Z')
        expect(props.dateTo).toBe('2026-06-11T09:00:00.000Z')
    })

    it('narrows to the inspected span when the scope toggle flips', () => {
        render(
            <Provider>
                <SpanMetricsTab span={span} />
            </Provider>
        )

        // LemonSegmentedButton renders each option label more than once; any instance works.
        fireEvent.click(screen.getAllByText('This span')[0])

        const props = capturedProps[capturedProps.length - 1]
        expect(props.spanId).toBe('span-xyz')
    })

    it('links to the span service metrics over the trace window', () => {
        render(
            <Provider>
                <SpanMetricsTab span={span} />
            </Provider>
        )

        const href = screen.getAllByText('View metrics').at(-1)?.closest('a')?.getAttribute('href')
        expect(href).toContain('billing-worker')
        // Same ±1h window the samples query uses, so the chart and the samples agree.
        expect(href).toContain('dateFrom=2026-06-11T07%3A00%3A00.000Z')
        expect(href).toContain('dateTo=2026-06-11T09%3A00%3A00.000Z')
    })

    it('moves the metrics link window when a different span is selected', () => {
        const otherSpan = {
            ...span,
            span_id: 'span-later',
            service_name: 'billing-api',
            timestamp: '2026-06-11T20:00:00.000Z',
        } as Span

        const { rerender } = render(
            <Provider>
                <SpanMetricsTab span={span} />
            </Provider>
        )
        rerender(
            <Provider>
                <SpanMetricsTab span={otherSpan} />
            </Provider>
        )

        const href = screen.getAllByText('View metrics').at(-1)?.closest('a')?.getAttribute('href')
        expect(href).toContain('billing-api')
        // The window follows the newly selected span, not the first span's.
        expect(href).toContain('dateFrom=2026-06-11T19%3A00%3A00.000Z')
        expect(href).toContain('dateTo=2026-06-11T21%3A00%3A00.000Z')
    })
})
