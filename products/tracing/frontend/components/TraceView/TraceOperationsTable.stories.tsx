import { Decorator, Meta, StoryObj } from '@storybook/react'

import { compareRowKey } from '../../compareUtils'
import type { TraceOperation } from '../../traceOperations'
import { TraceOperationsTable } from './TraceOperationsTable'

const ms = (value: number): number => value * 1_000_000

function operation(
    service_name: string,
    name: string,
    stats: Omit<TraceOperation, 'key' | 'service_name' | 'name'>
): TraceOperation {
    return { key: compareRowKey({ service_name, name }), service_name, name, ...stats }
}

// A 3.8 s checkout trace. The root's child spans do not overlap, so the self times add up to 3.8 s and each
// share is the self time over 3.8 s. The child spans have no children, so their self time is their total.
const OPERATIONS: TraceOperation[] = [
    operation('checkout-api', 'POST /api/orders', {
        count: 1,
        self_time_nano: ms(1898),
        total_duration_nano: ms(3800),
        avg_duration_nano: ms(3800),
        p50_duration_nano: ms(3800),
        share: 0.4995,
    }),
    operation('checkout-api', 'cache GET', {
        count: 1751,
        self_time_nano: ms(1200),
        total_duration_nano: ms(1200),
        avg_duration_nano: ms(0.685),
        p50_duration_nano: ms(0.61),
        share: 0.3158,
    }),
    operation('postgres', 'SELECT orders', {
        count: 22,
        self_time_nano: ms(480),
        total_duration_nano: ms(480),
        avg_duration_nano: ms(21.8),
        p50_duration_nano: ms(18.4),
        share: 0.1263,
    }),
    operation('inventory', 'reserveStock', {
        count: 4,
        self_time_nano: ms(210),
        total_duration_nano: ms(210),
        avg_duration_nano: ms(52.5),
        p50_duration_nano: ms(51),
        share: 0.0553,
    }),
    operation('notifications', 'enqueueEmail', {
        count: 1,
        self_time_nano: ms(12),
        total_duration_nano: ms(12),
        avg_duration_nano: ms(12),
        p50_duration_nano: ms(12),
        share: 0.0032,
    }),
]

// 30 operations of spans with no children, so each self time is the total. The self times fall by 2 ms per
// row and add up to 930 ms, so each share is the self time over 930 ms. The span counts rise by 1 per row, so
// a sort by Spans shows the other end of the list.
const MANY_OPERATIONS: TraceOperation[] = Array.from({ length: 30 }, (_, index) => {
    const total = ms(60 - index * 2)
    const count = index + 1
    return operation('catalog-api', `GET /items/${index + 1}`, {
        count,
        self_time_nano: total,
        total_duration_nano: total,
        avg_duration_nano: total / count,
        p50_duration_nano: total / count,
        share: total / ms(930),
    })
})

// The snapshot root shrinks to its content, so each story sets the width it snapshots at.
const fixedWidth =
    (className: string): Decorator =>
    (Story) => (
        <div className={className}>
            <Story />
        </div>
    )

const meta: Meta<typeof TraceOperationsTable> = {
    title: 'Products/Tracing/TraceOperationsTable',
    component: TraceOperationsTable,
    tags: ['autodocs'],
    args: {
        operations: OPERATIONS,
        highlightedOperationKey: null,
        onHighlightOperation: () => {},
    },
}
export default meta

type Story = StoryObj<typeof TraceOperationsTable>

export const Default: Story = {
    args: { highlightedOperationKey: compareRowKey({ service_name: 'checkout-api', name: 'cache GET' }) },
    decorators: [fixedWidth('w-[1100px]')],
}

/** The width of the trace drawer next to an open side panel, on a trace that has more spans to load. */
export const Narrow: Story = {
    args: { partial: true },
    decorators: [fixedWidth('w-[520px]')],
}

/**
 * A trace with more operations than the panel lists, so the note under the table shows. The panel shows
 * the top 5 by the sorted column.
 */
export const Capped: Story = {
    args: { operations: MANY_OPERATIONS },
    decorators: [fixedWidth('w-[1100px]')],
}
