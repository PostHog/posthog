import { fireEvent, render } from '@testing-library/react'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import type { Span } from '../../types'
import { SpanRowActions } from './SpanRowActions'

jest.mock('lib/utils/copyToClipboard', () => ({
    copyToClipboard: jest.fn(),
}))

const span = { trace_id: 'trace-abc-123', name: 'GET /api/projects', timestamp: '2026-06-11T08:00:00.000Z' } as Span

describe('SpanRowActions', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('renders the View trace and copy actions', () => {
        const { container } = render(<SpanRowActions span={span} onViewTrace={jest.fn()} />)
        expect(container.querySelector('[data-attr="tracing-view-trace"]')).toBeTruthy()
        expect(container.querySelector('[data-attr="tracing-copy-trace-id"]')).toBeTruthy()
        expect(container.querySelector('[data-attr="tracing-copy-link"]')).toBeTruthy()
    })

    it('fires onViewTrace when View trace is clicked', () => {
        const onViewTrace = jest.fn()
        const { container } = render(<SpanRowActions span={span} onViewTrace={onViewTrace} />)
        fireEvent.click(container.querySelector('[data-attr="tracing-view-trace"]')!)
        expect(onViewTrace).toHaveBeenCalledTimes(1)
    })

    it('copies the trace id', () => {
        const { container } = render(<SpanRowActions span={span} onViewTrace={jest.fn()} />)
        fireEvent.click(container.querySelector('[data-attr="tracing-copy-trace-id"]')!)
        expect(copyToClipboard).toHaveBeenCalledWith('trace-abc-123', 'trace ID')
    })

    it('copies a canonical trace link carrying the ts hint', () => {
        const { container } = render(<SpanRowActions span={span} onViewTrace={jest.fn()} />)
        fireEvent.click(container.querySelector('[data-attr="tracing-copy-link"]')!)
        expect(copyToClipboard).toHaveBeenCalledWith(
            `${window.location.origin}/tracing?trace=trace-abc-123&ts=2026-06-11T08%3A00%3A00.000Z`,
            'trace link'
        )
    })

    // Both buttons stop propagation so a click never reaches the row's own onClick. This matters most
    // for "View trace": in VirtualizedSpanList the row onClick and onViewTrace are the same handler, so
    // dropping stopPropagation would open the trace modal twice on a single click.
    it.each(['tracing-view-trace', 'tracing-copy-trace-id', 'tracing-copy-link'])(
        'stops %s clicks from bubbling to the row body',
        (dataAttr) => {
            const onRowClick = jest.fn()
            const { container } = render(
                // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events
                <div onClick={onRowClick}>
                    <SpanRowActions span={span} onViewTrace={jest.fn()} />
                </div>
            )
            fireEvent.click(container.querySelector(`[data-attr="${dataAttr}"]`)!)
            expect(onRowClick).not.toHaveBeenCalled()
        }
    )
})
