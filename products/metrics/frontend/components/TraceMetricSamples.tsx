import { useValues } from 'kea'

import { LemonBanner, LemonTable, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { metricUrl } from 'products/metrics/frontend/metricsLinks'

import { SampleAttributes } from './SampleAttributes'
import { traceMetricSamplesLogic } from './traceMetricSamplesLogic'

export interface TraceMetricSamplesProps {
    /** Hex trace id, as the tracing product uses. */
    traceId: string
    /** When set, only emissions recorded on this span (hex span id) are shown. */
    spanId?: string | null
    /** ISO window bounding the sample query, derived from the trace's timestamp. */
    dateFrom: string
    dateTo: string
}

// Metric emissions correlated with one trace (via OTel exemplars), each linking into the
// metrics viewer scoped to its metric — the reverse of the exemplar dots' metric->trace pivot.
export function TraceMetricSamples({ traceId, spanId, dateFrom, dateTo }: TraceMetricSamplesProps): JSX.Element {
    const { samples, samplesLoading, samplesError } = useValues(
        traceMetricSamplesLogic({ traceId, spanId, dateFrom, dateTo })
    )

    if (samplesError) {
        return (
            <LemonBanner type="error">
                Couldn't load the metrics for this trace. Close and reopen the trace to retry, and if it keeps happening
                contact support.
            </LemonBanner>
        )
    }

    return (
        <LemonTable
            dataSource={samples}
            loading={samplesLoading}
            size="small"
            rowKey={(sample, rowIndex) => `${rowIndex}-${sample.timestamp}-${sample.metric_name}`}
            emptyState={
                spanId
                    ? 'No metrics were recorded on this span. Counters and histograms with exemplars link here automatically.'
                    : 'No metrics were recorded on this trace. Counters and histograms with exemplars link here automatically.'
            }
            expandable={{
                expandedRowRender: (sample) => <SampleAttributes sample={sample} />,
            }}
            columns={[
                {
                    title: 'Timestamp',
                    key: 'timestamp',
                    width: 0,
                    render: (_, sample) => <TZLabel time={sample.timestamp} formatDate="MMM D" formatTime="HH:mm:ss" />,
                },
                {
                    title: 'Metric',
                    key: 'metric',
                    render: (_, sample) => (
                        <Tooltip title="Open this metric in the metrics viewer">
                            <Link
                                to={metricUrl({
                                    metricName: sample.metric_name,
                                    metricType: sample.metric_type || undefined,
                                    dateFrom,
                                    dateTo,
                                })}
                                className="font-mono"
                            >
                                {/* Link doesn't take data-attr; the span gives autocapture a named element. */}
                                <span data-attr="tracing-metrics-open-metric">{sample.metric_name}</span>
                            </Link>
                        </Tooltip>
                    ),
                },
                {
                    title: 'Value',
                    key: 'value',
                    align: 'right',
                    render: (_, sample) => (
                        <Tooltip
                            title={
                                sample.count > 1
                                    ? `Distribution sum over ${sample.count} observations${sample.unit ? ` (${sample.unit})` : ''}`
                                    : sample.unit || undefined
                            }
                        >
                            <span className="font-mono">{humanFriendlyNumber(sample.value, 2)}</span>
                        </Tooltip>
                    ),
                },
                {
                    title: 'Service',
                    key: 'service',
                    render: (_, sample) =>
                        sample.service_name ? (
                            <span className="truncate max-w-40">{sample.service_name}</span>
                        ) : (
                            <span className="text-secondary">—</span>
                        ),
                },
            ]}
        />
    )
}
