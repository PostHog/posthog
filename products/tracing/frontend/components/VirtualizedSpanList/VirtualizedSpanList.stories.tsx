import { Meta, StoryObj } from '@storybook/react'

import type { Span } from '../../types'
import { VirtualizedSpanList } from './VirtualizedSpanList'

const span = (index: number, overrides: Partial<Span> = {}): Span => ({
    uuid: `span-${index}`,
    trace_id: '842AF0A62764CA7B9E1D3F0C55A1B204',
    span_id: `0000000000000${index}`,
    parent_span_id: '00000000000000ff',
    name: 'validateReplayHeadersStep',
    kind: 3,
    service_name: 'ingestion-sessionreplay-metrics',
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
    span(2, { name: 'teamFilterStep' }),
    span(3, { name: 'applyEventRestrictionsStep', duration_nano: 390_000 }),
    span(4, { name: 'lazyLoader.loadViaCache', service_name: 'cdp-events-consumer-ws', duration_nano: 4_630_000 }),
    span(5, { name: 'parseHeadersStep', status_code: 2, duration_nano: 63_000 }),
]

const meta: Meta<typeof VirtualizedSpanList> = {
    title: 'Products/Tracing/VirtualizedSpanList',
    component: VirtualizedSpanList,
    tags: ['autodocs'],
    decorators: [
        (Story) => (
            <div className="flex flex-col h-100">
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
