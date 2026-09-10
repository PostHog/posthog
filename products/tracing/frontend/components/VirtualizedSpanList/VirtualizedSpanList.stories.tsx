import { Meta, StoryObj } from '@storybook/react'

import type { Span } from '../../types'
import { VirtualizedSpanList } from './VirtualizedSpanList'

const span = (index: number, overrides: Partial<Span> = {}): Span => ({
    uuid: `span-${index}`,
    trace_id: '0F3B7C1A5E2D48960B7A1C3E5D9F2048',
    span_id: `000000000000000${index}`,
    parent_span_id: '00000000000000ff',
    name: 'loadCartContents',
    kind: 3,
    // Long enough to show that the service column no longer truncates.
    service_name: 'checkout-orchestrator-europe',
    status_code: 1,
    timestamp: '2026-08-28T10:24:27.000Z',
    end_time: '2026-08-28T10:24:27.000Z',
    duration_nano: 18_000,
    is_root_span: false,
    matched_filter: true,
    attributes: {},
    resource_attributes: {},
    ...overrides,
})

const SPANS: Span[] = [
    span(1, { parent_span_id: '', is_root_span: true, name: 'POST /api/v2/checkout/session/confirm' }),
    span(2, { name: 'validateCoupon' }),
    span(3, { name: 'reserveStockForOrder', duration_nano: 390_000 }),
    span(4, { name: 'pricing.quoteFromCache', service_name: 'pricing-api', duration_nano: 4_630_000 }),
    span(5, { name: 'chargePaymentMethod', status_code: 2, duration_nano: 63_000 }),
]

const meta: Meta<typeof VirtualizedSpanList> = {
    title: 'Products/Tracing/VirtualizedSpanList',
    component: VirtualizedSpanList,
    tags: ['autodocs'],
    decorators: [
        (Story) => (
            // A definite width, not just height: without one, AutoSizer and Storybook's
            // shrink-to-fit layout chase each other's size forever.
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', flexDirection: 'column', width: 1300, height: 400 }}>
                <Story />
            </div>
        ),
    ],
    args: {
        dataSource: SPANS,
        loading: false,
        orderBy: 'timestamp',
        orderDirection: 'DESC',
        onSort: () => {},
        onRowClick: () => {},
        onVisibleRowRangeChange: () => {},
    },
}
export default meta

type Story = StoryObj<typeof VirtualizedSpanList>

export const Default: Story = {}

export const Empty: Story = {
    args: { dataSource: [] },
}
