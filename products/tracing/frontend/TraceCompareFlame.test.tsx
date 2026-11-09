import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { getChart } from '@posthog/quill-charts/testing'

import type { SpanTreeNode } from '~/queries/schema/schema-general'

import { TraceCompareFlame } from './TraceCompareFlame'
import { buildTree } from './traceFlameTree'

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

    // A null `previous` still means compare mode; only a given tree is a single trace.
    it.each([
        { label: 'the compare modal without previous rows', tree: undefined, shown: 'Similar', hidden: 'checkout-api' },
        {
            label: 'a single trace',
            tree: buildTree([row('cache GET', 3)], null),
            shown: 'checkout-api',
            hidden: 'Similar',
        },
    ])('shows the right legend for $label', ({ tree, shown, hidden }) => {
        render(
            <TraceCompareFlame
                tree={tree}
                current={[row('cache GET', 3)]}
                previous={null}
                loading={false}
                surface="compare_modal"
            />
        )

        const labels = getChart()
            .legendItems()
            .map((item) => item.label)
        expect(labels).toContain(shown)
        expect(labels).not.toContain(hidden)
    })
})
