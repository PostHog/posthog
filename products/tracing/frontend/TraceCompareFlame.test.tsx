import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { SpanTreeNode } from '~/queries/schema/schema-general'

import { TraceCompareFlame } from './TraceCompareFlame'

const row = (name: string, count: number): SpanTreeNode => ({
    parent_service: '',
    parent_name: '<ROOT>',
    service_name: 'checkout-api',
    name,
    count,
    total_duration_nano: count * 1_000_000,
    avg_duration_nano: 1_000_000,
    p50_duration_nano: 1_000_000,
    p95_duration_nano: 1_000_000,
    p99_duration_nano: 1_000_000,
    p999_duration_nano: 1_000_000,
    error_count: 0,
    avg_start_offset_nano: 0,
    calls_per_parent_invocation: null,
})

describe('TraceCompareFlame', () => {
    afterEach(() => {
        cleanup()
    })

    // The compare modal passes a null `previous` before its first tree fetch ends, and when the response has no
    // comparison rows. Only a given call tree is a single trace, so a flame that reads a null `previous` as one drops
    // the modal's legend and relabels its bars.
    it('keeps the compare legend and plain labels in the compare modal without previous rows', () => {
        render(
            <TraceCompareFlame
                current={[row('cache GET', 3)]}
                previous={null}
                loading={false}
                surface="compare_modal"
            />
        )

        expect(screen.getByText('vanished')).toBeInTheDocument()
        expect(screen.getByText('cache GET')).toBeInTheDocument()
        expect(screen.queryByText('cache GET ×3')).toBeNull()
    })
})
