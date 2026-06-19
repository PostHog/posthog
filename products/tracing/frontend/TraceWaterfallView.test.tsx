import { fireEvent, render, within } from '@testing-library/react'

import { TraceWaterfallView } from './TraceWaterfallView'
import type { Span } from './types'

// Give the waterfall real dimensions so react-window renders rows (ResizeObserver is mocked globally
// in jest.setup.ts; AutoSizer returns 0×0 in jsdom without this).
jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 600, width: 800 }),
}))

// uuid (ClickHouse row id) and span_id (OTel id) are deliberately DISTINCT so a test can tell which
// identity the click emits — the inspector/URL/tree all key on span_id, so selection must too.
function makeSpan(overrides: Partial<Span>): Span {
    return {
        uuid: 'uuid-x',
        trace_id: 'trace-1',
        span_id: 'span-x',
        parent_span_id: '',
        name: 'span',
        kind: 1,
        service_name: 'svc',
        status_code: 0,
        timestamp: '2026-06-11T08:00:00.000Z',
        end_time: '2026-06-11T08:00:00.010Z',
        duration_nano: 10_000_000,
        is_root_span: false,
        matched_filter: true,
        attributes: {},
        resource_attributes: {},
        ...overrides,
    }
}

const root = makeSpan({ uuid: 'uuid-root', span_id: 'span-root', name: 'root-operation', is_root_span: true })
const child = makeSpan({
    uuid: 'uuid-child',
    span_id: 'span-child',
    parent_span_id: 'span-root',
    name: 'child-operation',
})

describe('TraceWaterfallView', () => {
    // Scope to the render's own container (no auto-cleanup here, and the name renders in both the
    // visible label and the Lemon Tooltip title — [0] is the label).
    const clickSpanRow = (container: HTMLElement, name: string): void => {
        fireEvent.click(within(container).getAllByText(name)[0])
    }

    it('emits the clicked span_id (not the row uuid) so the inspector and URL can resolve it', () => {
        const onSpanSelect = jest.fn()
        const { container } = render(<TraceWaterfallView spans={[root, child]} onSpanSelect={onSpanSelect} />)

        clickSpanRow(container, 'child-operation')

        expect(onSpanSelect).toHaveBeenCalledWith('span-child')
        expect(onSpanSelect).not.toHaveBeenCalledWith('uuid-child')
    })

    it('toggles selection off when the same span is clicked twice', () => {
        // Controlled: the parent (scene) flows the new selection back via the prop, so the second
        // click sees `child` selected and emits null. Simulate that round-trip with a rerender.
        const onSpanSelect = jest.fn()
        const { container, rerender } = render(<TraceWaterfallView spans={[root, child]} onSpanSelect={onSpanSelect} />)

        clickSpanRow(container, 'child-operation')
        rerender(<TraceWaterfallView spans={[root, child]} selectedSpanId="span-child" onSpanSelect={onSpanSelect} />)
        clickSpanRow(container, 'child-operation')

        expect(onSpanSelect).toHaveBeenNthCalledWith(1, 'span-child')
        expect(onSpanSelect).toHaveBeenNthCalledWith(2, null)
    })
})
