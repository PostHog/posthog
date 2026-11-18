import { Meta, StoryObj } from '@storybook/react'

import type { _ServiceHealthRowApi } from 'products/tracing/frontend/generated/api.schemas'

import { ServicesTable } from './ServicesTable'

const ROWS: _ServiceHealthRowApi[] = [
    {
        service: 'checkout-api',
        status: 'regressed',
        reason: 'error rate 0.4% → 3.2%',
        requests: 1_284_004,
        throughput_per_min: 21_400,
        error_count: 41_088,
        error_rate_pct: 3.2,
        error_rate_delta_pp: 2.8,
        p50_ms: 120,
        p95_ms: 565.6,
        p95_change_pct: 38.2,
        p99_ms: 936.3,
        baseline_requests: 1_190_220,
        last_seen: '2026-06-02T08:59:58Z',
    },
    {
        service: 'inventory-worker',
        status: 'ok',
        reason: '',
        requests: 511_222,
        throughput_per_min: 8_520,
        error_count: 1_402,
        error_rate_pct: 0.27,
        error_rate_delta_pp: -0.05,
        p50_ms: 210,
        p95_ms: 694.7,
        p95_change_pct: -4.1,
        p99_ms: 903.3,
        baseline_requests: 498_000,
        last_seen: '2026-06-02T08:59:59Z',
    },
    {
        service: 'notifications',
        status: 'new',
        reason: 'no spans in baseline window',
        requests: 96_310,
        throughput_per_min: 1_605,
        error_count: 0,
        error_rate_pct: 0,
        error_rate_delta_pp: null,
        p50_ms: 89.1,
        p95_ms: 184,
        p95_change_pct: null,
        p99_ms: 195,
        baseline_requests: 0,
        last_seen: '2026-06-02T08:59:57Z',
    },
]

const meta: Meta<typeof ServicesTable> = {
    title: 'Products/Tracing/ServicesTable',
    component: ServicesTable,
    tags: ['autodocs'],
    decorators: [
        (Story) => (
            // A definite width, not just height: without one, AutoSizer and Storybook's
            // shrink-to-fit layout chase each other's size forever.
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', flexDirection: 'column', width: 1100, height: 320 }}>
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof ServicesTable>

export const Default: Story = {
    args: { rows: ROWS, loading: false, windowMs: 3_600_000 },
}

export const Empty: Story = {
    args: { rows: [], loading: false, windowMs: 3_600_000 },
}
