import { render } from '@testing-library/react'

import type { Span } from '../../types'
import { SpanLogsTab } from './SpanLogsTab'

// Capture the props the embedded LogsViewer receives. The logsViewerFiltersLogic compares
// `initialFilters` by IDENTITY (propsChanged uses `!==`), so a fresh object each render re-applies
// setFilters → re-query. A drawer resize re-renders this component on every mousemove, so the prop
// objects must be referentially stable across re-renders with the same span.
const capturedProps: { pinnedFilters: unknown; initialFilters: unknown }[] = []
jest.mock('products/logs/frontend/components/LogsViewer/LogsViewer', () => ({
    LogsViewer: (props: { pinnedFilters: unknown; initialFilters: unknown }) => {
        capturedProps.push({ pinnedFilters: props.pinnedFilters, initialFilters: props.initialFilters })
        return null
    },
}))

const span = {
    trace_id: 'trace-abc',
    span_id: 'span-xyz',
    timestamp: '2026-06-11T08:00:00.000Z',
} as Span

describe('SpanLogsTab', () => {
    beforeEach(() => {
        capturedProps.length = 0
    })

    it('passes referentially stable pinnedFilters/initialFilters across re-renders (no re-query on resize)', () => {
        const { rerender } = render(<SpanLogsTab span={span} />)
        const first = capturedProps[capturedProps.length - 1]

        // Re-render with the same span (mirrors a parent re-render from a resize drag).
        rerender(<SpanLogsTab span={span} />)
        const second = capturedProps[capturedProps.length - 1]

        expect(second.pinnedFilters).toBe(first.pinnedFilters)
        expect(second.initialFilters).toBe(first.initialFilters)
    })
})
