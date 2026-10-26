import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { type ReactElement, type ReactNode } from 'react'

import { TraceWaterfallView, type TraceWaterfallSpan } from './TraceWaterfallView'

jest.mock(
    '@posthog/mcp-ui',
    () => ({
        cn: (...classes: unknown[]): string => classes.filter(Boolean).join(' '),
        DescriptionList: ({ items }: { items: { label: string; value: string }[] }): ReactElement => (
            <dl>
                {items.map((item) => (
                    <div key={item.label}>
                        <dt>{item.label}</dt>
                        <dd>{item.value}</dd>
                    </div>
                ))}
            </dl>
        ),
    }),
    { virtual: true }
)

jest.mock(
    '@posthog/quill',
    () => ({
        Badge: ({ children }: { children: ReactNode }): ReactElement => <span>{children}</span>,
        Button: ({ children, onClick }: { children: ReactNode; onClick: () => void }): ReactElement => (
            <button type="button" onClick={onClick}>
                {children}
            </button>
        ),
    }),
    { virtual: true }
)

function span(spanId: string, parentSpanId: string, overrides: Partial<TraceWaterfallSpan> = {}): TraceWaterfallSpan {
    return {
        uuid: spanId,
        trace_id: 'abc123',
        span_id: spanId,
        parent_span_id: parentSpanId,
        name: `${spanId} span`,
        kind: 2,
        service_name: 'checkout',
        status_code: 1,
        timestamp: '2026-10-14T10:00:00.000000Z',
        end_time: '2026-10-14T10:00:01.000000Z',
        duration_nano: 1_000_000_000,
        is_root_span: parentSpanId === '',
        ...overrides,
    }
}

function spanNames(): string[] {
    return screen.getAllByRole('button', { pressed: false }).map((row) => row.getAttribute('aria-label') ?? '')
}

describe('TraceWaterfallView', () => {
    afterEach(cleanup)

    it('nests spans under their parent and hides them when the parent collapses', () => {
        render(
            <TraceWaterfallView
                data={{
                    results: [
                        span('root', ''),
                        span('db', 'root', { timestamp: '2026-10-14T10:00:00.200000Z', duration_nano: 300_000_000 }),
                        span('cache', 'root', { timestamp: '2026-10-14T10:00:00.100000Z', duration_nano: 50_000 }),
                    ],
                }}
            />
        )

        expect(screen.getByRole('button', { pressed: true })).toHaveAccessibleName('root span')
        expect(spanNames()).toEqual(['cache span', 'db span'])

        fireEvent.click(screen.getByRole('button', { name: 'Hide 2 nested spans' }))

        expect(screen.queryAllByRole('button', { pressed: false })).toHaveLength(0)
    })

    // excludeAttributes drops the attribute maps, and a partial trace can lose a parent span.
    it('renders a trace with no attribute maps and a missing parent', () => {
        render(
            <TraceWaterfallView
                data={{
                    results: [
                        span('orphan', 'gone', { status_code: 2 }),
                        span('child', 'orphan', { attributes: { 'http.route': '/cart' } }),
                    ],
                    hasMore: true,
                }}
            />
        )

        expect(screen.getByText('1 error')).toBeInTheDocument()
        expect(screen.getByText(/Showing the first 2 spans/)).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'child span' }))

        expect(screen.getByText('http.route')).toBeInTheDocument()
        expect(screen.getByText('/cart')).toBeInTheDocument()
    })
})
