import { Meta, StoryObj } from '@storybook/react'

import { AggregatedSpanRow } from '~/queries/schema/schema-general'

import { OperationsTable } from './OperationsTable'

const ms = (value: number): number => value * 1_000_000

const ROWS: AggregatedSpanRow[] = [
    {
        service_name: 'checkout-api',
        name: 'POST /api/v2/checkout/session/confirm',
        count: 1_284_004,
        error_count: 0,
        p50_duration_nano: ms(372.8),
        p95_duration_nano: ms(565.6),
        p99_duration_nano: ms(936.3),
        p999_duration_nano: ms(1290),
        total_duration_nano: ms(387_675_574),
    },
    {
        service_name: 'inventory-worker-europe',
        name: 'reserveStockForOrder',
        count: 511_222,
        error_count: 1402,
        p50_duration_nano: ms(442.2),
        p95_duration_nano: ms(694.7),
        p99_duration_nano: ms(903.3),
        p999_duration_nano: ms(1240),
        total_duration_nano: ms(232_285_822),
    },
    {
        service_name: 'notifications',
        name: 'sendEmail',
        count: 96_310,
        error_count: 0,
        p50_duration_nano: ms(89.1),
        p95_duration_nano: ms(184),
        p99_duration_nano: ms(195),
        p999_duration_nano: ms(205),
        total_duration_nano: ms(9_921_866),
    },
] as AggregatedSpanRow[]

const meta: Meta<typeof OperationsTable> = {
    title: 'Products/Tracing/OperationsTable',
    component: OperationsTable,
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
}
export default meta

type Story = StoryObj<typeof OperationsTable>

export const Default: Story = {
    args: { rows: ROWS, loading: false, windowMs: 3_600_000 },
}

export const Empty: Story = {
    args: { rows: [], loading: false, windowMs: 3_600_000 },
}

export const Loading: Story = {
    args: { rows: [], loading: true, windowMs: 3_600_000 },
    parameters: {
        // The spinner never resolves, so don't wait for it to disappear before snapshotting.
        testOptions: { waitForLoadersToDisappear: false },
    },
}
