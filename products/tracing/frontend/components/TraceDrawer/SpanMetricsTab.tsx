import { useMemo, useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { TraceMetricSamples } from 'products/metrics/frontend/components/TraceMetricSamples'
import { ViewServiceMetricsButton } from 'products/metrics/frontend/components/ViewServiceMetricsButton'

import { traceLookupDateRange } from '../../traceLinks'
import type { Span } from '../../types'

type TraceMetricScope = 'trace' | 'span'

// Metric emissions correlated to the whole trace (default) or the inspected span, via OTel
// exemplars. Trace scope is the default because a single span rarely carries an exemplar of
// its own; narrow to the span with the toggle when needed.
export function SpanMetricsTab({ span }: { span: Span }): JSX.Element {
    const [scope, setScope] = useState<TraceMetricScope>('trace')

    // The samples endpoint needs a concrete ISO window; ±1h around the span covers any of
    // its emissions (same window cold trace loads use). Keyed by span timestamp so selecting
    // another span in the mounted drawer moves the samples query and the metrics pivot to the
    // new span's window.
    const dateRange = useMemo(
        () => traceLookupDateRange(dayjs(span.timestamp).isValid() ? span.timestamp : dayjs().toISOString()),
        [span.timestamp]
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
                {/* Exemplar samples below answer "which emissions carried this trace"; the pivot
                    answers "what was the host doing" by opening the service's own metric charts
                    over the same window. */}
                <ViewServiceMetricsButton
                    serviceName={span.service_name}
                    dateFrom={dateRange.date_from}
                    dateTo={dateRange.date_to}
                    size="xsmall"
                    type="secondary"
                    data-attr="tracing-metrics-open-service-metrics"
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
