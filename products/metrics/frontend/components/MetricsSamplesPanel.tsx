import { useActions, useValues } from 'kea'

import { LemonTable, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'
import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { type MetricsAggregateRow, type MetricsPanelTab, metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsViewerLogic } from './metricsViewerLogic'

function SampleAttributes({ sample }: { sample: _MetricEventSampleApi }): JSX.Element {
    const entries = [...Object.entries(sample.attributes), ...Object.entries(sample.resource_attributes)]
    if (!entries.length) {
        return <div className="text-secondary text-xs p-2">No attributes on this emission.</div>
    }
    return (
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 p-2 text-xs">
            {entries.map(([key, value]) => (
                <>
                    <span key={`${key}-k`} className="text-secondary font-mono">
                        {key}
                    </span>
                    <span key={`${key}-v`} className="font-mono break-all">
                        {value}
                    </span>
                </>
            ))}
        </div>
    )
}

function SamplesTab(): JSX.Element {
    const { samples, samplesLoading } = useValues(metricsSamplesLogic)
    const { hasMetricName } = useValues(metricsViewerLogic)

    return (
        <LemonTable
            dataSource={samples}
            loading={samplesLoading}
            size="small"
            rowKey={(sample) => `${sample.timestamp}-${sample.trace_id}-${sample.value}`}
            emptyState={
                hasMetricName
                    ? 'No emissions for this metric in the selected range.'
                    : 'Pick a metric to see its raw emissions.'
            }
            expandable={{
                expandedRowRender: (sample) => <SampleAttributes sample={sample} />,
            }}
            columns={[
                {
                    title: 'Timestamp',
                    key: 'timestamp',
                    render: (_, sample) => <TZLabel time={sample.timestamp} formatDate="MMM D" formatTime="HH:mm:ss" />,
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
                    title: 'Trace',
                    key: 'trace',
                    render: (_, sample) =>
                        sample.trace_id ? (
                            <Tooltip title="Open the trace this emission was recorded in">
                                <Link
                                    to={traceUrl({
                                        traceId: sample.trace_id,
                                        spanId: sample.span_id || null,
                                        ts: sample.timestamp,
                                    })}
                                    className="font-mono"
                                >
                                    {sample.trace_id.slice(0, 8).toLowerCase()}
                                </Link>
                            </Tooltip>
                        ) : (
                            <span className="text-secondary">—</span>
                        ),
                },
            ]}
        />
    )
}

function AggregatesTab(): JSX.Element {
    const { aggregateRows } = useValues(metricsSamplesLogic)
    const { queryResultsLoading, hasMetricName } = useValues(metricsViewerLogic)

    return (
        <LemonTable
            dataSource={aggregateRows}
            loading={queryResultsLoading}
            size="small"
            rowKey={(row: MetricsAggregateRow) => row.name}
            emptyState={
                hasMetricName ? 'No series in the selected range.' : 'Pick a metric to see per-series aggregates.'
            }
            columns={[
                {
                    title: 'Series',
                    key: 'series',
                    render: (_, row) => (
                        <span className="flex items-center gap-1.5">
                            <span
                                className="w-2 h-2 rounded-full shrink-0"
                                // Dynamic per-series colour can't be a Tailwind class.
                                style={{ backgroundColor: getColorVar(row.color) }}
                            />
                            <span className="truncate max-w-40" title={row.name}>
                                {row.name}
                            </span>
                        </span>
                    ),
                },
                {
                    title: 'Latest',
                    key: 'latest',
                    align: 'right',
                    render: (_, row) => <span className="font-mono">{humanFriendlyNumber(row.latest, 2)}</span>,
                },
                {
                    title: 'Total',
                    key: 'total',
                    align: 'right',
                    render: (_, row) => <span className="font-mono">{humanFriendlyNumber(row.total, 2)}</span>,
                },
            ]}
        />
    )
}

/** Side panel next to the chart: per-series aggregates, or the raw emissions
 * behind the chart with a link to the trace each one was recorded in. */
export function MetricsSamplesPanel(): JSX.Element {
    const { activeTab } = useValues(metricsSamplesLogic)
    const { setActiveTab } = useActions(metricsSamplesLogic)

    return (
        <div className="border rounded p-2 overflow-y-auto">
            <LemonTabs<MetricsPanelTab>
                size="small"
                activeKey={activeTab}
                onChange={setActiveTab}
                tabs={[
                    { key: 'aggregates', label: 'Aggregates', content: <AggregatesTab /> },
                    { key: 'samples', label: 'Samples', content: <SamplesTab /> },
                ]}
            />
        </div>
    )
}
