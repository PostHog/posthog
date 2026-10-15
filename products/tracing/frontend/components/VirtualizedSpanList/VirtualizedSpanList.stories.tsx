import { Meta, StoryObj } from '@storybook/react'

import type { Span } from '../../types'
import { DEFAULT_SPAN_COLUMNS } from './spanColumns'
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
        spanColumns: DEFAULT_SPAN_COLUMNS,
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

// One row per badge tier, plus two rows with no errors, so the column's alignment shows.
export const SpansView: Story = {
    args: { showRootTag: true },
}

export const WithErrorBadges: Story = {
    args: {
        spanErrors: {
            badges: new Map([
                ['span-1', { tier: 'trace', count: 4 }],
                ['span-3', { tier: 'session', count: 9 }],
                ['span-5', { tier: 'span', count: 1 }],
            ]),
            onShow: () => {},
        },
    },
}

export const CustomColumns: Story = {
    args: {
        dataSource: SPANS.map((span, index) => ({
            ...span,
            attributes: { 'http.target': index % 2 === 0 ? '/api/v2/checkout/session/confirm' : '' },
        })),
        spanColumns: [
            { type: 'timestamp' },
            { type: 'name' },
            { type: 'attribute', attributeKey: 'http.target' },
            { type: 'duration' },
        ],
    },
}

export const WithOrphanTrace: Story = {
    args: {
        dataSource: [
            span(1, {
                parent_span_id: '',
                is_root_span: true,
                name: 'POST /api/v2/checkout/session/confirm',
                timestamp: '2026-08-28T10:24:29.000Z',
            }),
            span(2, {
                trace_id: '7C2E9A4B1D6F43058E1B2A9C7D4F6E31',
                name: 'GET /api/v2/cart',
                kind: 2,
                service_name: 'cart-api',
                duration_nano: 42_000_000,
                timestamp: '2026-08-28T10:24:28.000Z',
                root_missing: true,
            }),
            span(3, {
                trace_id: '2A8D5F0C3B9E41A7962C4E8B1F0D7A53',
                parent_span_id: '',
                is_root_span: true,
                name: 'GET /api/v2/orders',
                duration_nano: 9_200_000,
            }),
        ],
    },
}
