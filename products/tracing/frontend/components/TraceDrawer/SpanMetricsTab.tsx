import { useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { TraceMetricSamples } from 'products/metrics/frontend/components/TraceMetricSamples'

import { traceLookupDateRange } from '../../traceLinks'
import type { Span } from '../../types'

type TraceMetricScope = 'trace' | 'span'

// Metric emissions correlated to the whole trace (default) or the inspected span, via OTel
// exemplars. Trace scope is the default because a single span rarely carries an exemplar of
// its own; narrow to the span with the toggle when needed.
export function SpanMetricsTab({ span }: { span: Span }): JSX.Element {
    const [scope, setScope] = useState<TraceMetricScope>('trace')

    // The samples endpoint needs a concrete ISO window; ±1h around the trace covers any of
    // its emissions (same window cold trace loads use). Computed once per mount: the drawer
    // remounts this tab per trace, and pinning the window here keeps span selection from
    // shifting it a few milliseconds and refetching for nothing.
    const [dateRange] = useState(() =>
        traceLookupDateRange(dayjs(span.timestamp).isValid() ? span.timestamp : dayjs().toISOString())
    )

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <LemonSegmentedButton
                    size="xsmall"
                    value={scope}
                    onChange={setScope}
                    options={[
                        { value: 'trace', label: 'Whole trace' },
                        { value: 'span', label: 'This span' },
                    ]}
                    data-attr="tracing-metrics-scope"
                />
            </div>
            <TraceMetricSamples
                traceId={span.trace_id}
                spanId={scope === 'span' ? span.span_id : null}
                dateFrom={dateRange.date_from}
                dateTo={dateRange.date_to}
            />
        </div>
    )
}
