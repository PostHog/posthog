import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { compareRowKey } from '../../compareUtils'
import type { TraceOperation } from '../../traceOperations'
import { TraceOperationsTable } from './TraceOperationsTable'

// Give the table real dimensions so react-window renders its rows. AutoSizer measures 0x0 in jsdom.
jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 600, width: 800 }),
}))

function makeOperation(
    service_name: string,
    name: string,
    self_time_nano: number,
    count = 1,
    total_duration_nano = self_time_nano
): TraceOperation {
    return {
        key: compareRowKey({ service_name, name }),
        service_name,
        name,
        count,
        self_time_nano,
        total_duration_nano,
        avg_duration_nano: total_duration_nano / count,
        p50_duration_nano: total_duration_nano / count,
        share: self_time_nano / 3_000_000,
    }
}

const orders = makeOperation('checkout-api', 'POST /api/orders', 2_000_000)
const cache = makeOperation('checkout-api', 'cache GET', 1_000_000)

describe('TraceOperationsTable', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => cleanup())

    it('highlights the clicked operation and clears the highlight when the same operation is clicked again', () => {
        // The second click must emit null. If it emits the key again, a click on the table can never
        // clear the dimming in the span tree. The clicks go through the keyboard-reachable button, so
        // the test also fails when one click toggles twice (the button and then its row), or when the
        // button stops telling assistive technology which operation is highlighted.
        const onHighlightOperation = jest.fn()
        const { rerender } = render(
            <TraceOperationsTable
                operations={[orders, cache]}
                highlightedOperationKey={null}
                onHighlightOperation={onHighlightOperation}
            />
        )
        // Text query, not a role query: role queries walk the whole DOM and are slow in jsdom.
        const ordersButton = (): HTMLElement => screen.getByText('POST /api/orders').closest('button') as HTMLElement
        expect(ordersButton().getAttribute('aria-pressed')).toBe('false')

        fireEvent.click(ordersButton())
        rerender(
            <TraceOperationsTable
                operations={[orders, cache]}
                highlightedOperationKey={orders.key}
                onHighlightOperation={onHighlightOperation}
            />
        )
        expect(ordersButton().getAttribute('aria-pressed')).toBe('true')
        fireEvent.click(ordersButton())

        expect(onHighlightOperation.mock.calls).toEqual([[orders.key], [null]])
    })

    it.each([
        // Fails when the cap keeps the wrong end of the list, or when the rows sort by total: op-29 has the least
        // self time and the largest total.
        { sortedBy: 'self time', header: null, shown: 'op-0', hidden: 'op-29' },
        // Fails when the cap runs before the sort. That cap keeps the five largest self times, so op-0, the
        // operation with the fewest spans, stays and op-29, the one with the most, never shows.
        { sortedBy: 'span count', header: 'Spans', shown: 'op-29', hidden: 'op-0' },
    ])('renders only the top operations by $sortedBy and says how many there are', ({ header, shown, hidden }) => {
        // A trace with many operations must not render every row. The span counts and the totals rise as the
        // self times fall, so the two sorts keep opposite ends of the list.
        const operations = Array.from({ length: 30 }, (_, index) =>
            makeOperation('catalog-api', `op-${index}`, (30 - index) * 1_000_000, index + 1, (index + 1) * 10_000_000)
        )
        const { container } = render(
            <TraceOperationsTable
                operations={operations}
                highlightedOperationKey={null}
                onHighlightOperation={jest.fn()}
            />
        )
        if (header) {
            fireEvent.click(screen.getByText(header))
        }

        expect(container.querySelectorAll('button[data-attr="tracing-trace-operations-highlight"]')).toHaveLength(5)
        expect(screen.getByText('Showing 5 of 30 operations.')).toBeTruthy()
        expect(screen.getByText(shown)).toBeTruthy()
        expect(screen.queryByText(hidden)).toBeNull()
    })
})
