import { useActions, useValues } from 'kea'
import { Fragment, useState } from 'react'

import { LemonSegmentedButton, LemonTable, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { traceUrl } from 'products/tracing/frontend/traceLinks'

import { type MetricsSeriesRow, type MetricsPanelTab, metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { metricsViewerLogic } from './metricsViewerLogic'
import { SampleAttributes } from './SampleAttributes'

function SamplesTab(): JSX.Element {
    const { samples, samplesLoading } = useValues(metricsSamplesLogic)
    const { hasMetricName } = useValues(metricsViewerLogic)
    const { timezone } = useValues(teamLogic)
    const { sampleRowExpanded, tracePivotClicked } = useActions(metricsUsageTrackingLogic)
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )

    return (
        <LemonTable
            dataSource={samples}
            loading={samplesLoading}
            size="small"
            rowKey={(sample, rowIndex) => `${rowIndex}-${sample.timestamp}-${sample.trace_id}`}
            emptyState={
                hasMetricName
                    ? 'No emissions for this metric in the selected range.'
                    : 'Pick a metric to see its raw emissions.'
            }
            expandable={{
                expandedRowRender: (sample) => <SampleAttributes sample={sample} />,
                onRowExpand: (sample) => sampleRowExpanded(sample),
            }}
            columns={[
                {
                    title: 'Timestamp',
                    key: 'timestamp',
                    render: (_, sample) => (
                        <TZLabel
                            time={sample.timestamp}
                            formatDate="MMM D"
                            formatTime="HH:mm:ss"
                            displayTimezone={timezone}
                        />
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
                    title: 'Trace',
                    key: 'trace',
                    render: (_, sample) =>
                        sample.trace_id && !tracingDisabledReason ? (
                            <Tooltip title="Open the trace this emission was recorded in">
                                <Link
                                    to={traceUrl({
                                        traceId: sample.trace_id,
                                        spanId: sample.span_id || null,
                                        ts: sample.timestamp,
                                    })}
                                    className="font-mono"
                                    onClick={() => tracePivotClicked(sample)}
                                >
                                    {/* Link doesn't take data-attr; the span gives autocapture a named element. */}
                                    <span data-attr="metrics-trace-pivot">
                                        {sample.trace_id.slice(0, 8).toLowerCase()}
                                    </span>
                                </Link>
                            </Tooltip>
                        ) : sample.trace_id ? (
                            <Tooltip title={tracingDisabledReason}>
                                <span className="font-mono text-secondary cursor-not-allowed">
                                    {sample.trace_id.slice(0, 8).toLowerCase()}
                                </span>
                            </Tooltip>
                        ) : (
                            <span className="text-secondary">—</span>
                        ),
                },
            ]}
        />
    )
}

/** One `key=value` label with the key muted, so the values are easy to scan. */
function SeriesNamePart({ part }: { part: string }): JSX.Element {
    const separatorIndex = part.indexOf('=')
    if (separatorIndex < 1) {
        return <>{part}</>
    }
    return (
        <>
            <span className="text-tertiary">{part.slice(0, separatorIndex + 1)}</span>
            {part.slice(separatorIndex + 1)}
        </>
    )
}

function SeriesTab(): JSX.Element {
    const { seriesRows } = useValues(metricsSamplesLogic)
    const { queryLoading, hasMetricName } = useValues(metricsViewerLogic)
    const { seriesRowExpanded } = useActions(metricsUsageTrackingLogic)
    const [expandedNames, setExpandedNames] = useState<string[]>([])

    return (
        <LemonTable
            dataSource={seriesRows}
            loading={queryLoading}
            size="small"
            rowKey={(row: MetricsSeriesRow) => row.name}
            emptyState={hasMetricName ? 'No series in the selected range.' : 'Pick a metric to see its series.'}
            expandable={{
                noIndent: true,
                // The first label stays on the row line, so the row reads as one box that grows.
                expandedRowRender: (row) => (
                    <div className="flex flex-col gap-1 pb-2.5 pr-4 pl-[4.375rem]">
                        {row.nameParts.slice(1).map((part, index) => (
                            <span key={index} className="wrap-anywhere">
                                <SeriesNamePart part={part} />
                            </span>
                        ))}
                    </div>
                ),
                expandedRowClassName: '!border-t-0 !bg-surface-primary',
                rowExpandable: (row) => row.hasLabels,
                isRowExpanded: (row) => expandedNames.includes(row.name),
                onRowExpand: (row) => {
                    setExpandedNames([...expandedNames, row.name])
                    seriesRowExpanded()
                },
                onRowCollapse: (row) => setExpandedNames(expandedNames.filter((name) => name !== row.name)),
            }}
            columns={[
                {
                    title: 'Series',
                    key: 'series',
                    width: '100%',
                    render: (_, row) => (
                        <span className="flex items-center gap-1.5">
                            <span
                                className="w-2 h-2 rounded-full shrink-0"
                                // Dynamic per-series colour can't be a Tailwind class.
                                style={{ backgroundColor: getColorVar(row.color) }}
                            />
                            {/* w-0 + min-w-full fills the column without the text widening it. */}
                            {expandedNames.includes(row.name) ? (
                                <span className="w-0 min-w-full wrap-anywhere">
                                    <SeriesNamePart part={row.nameParts[0]} />
                                </span>
                            ) : (
                                <span className="w-0 min-w-full truncate" title={row.name}>
                                    {row.nameParts.map((part, index) => (
                                        <Fragment key={index}>
                                            {index > 0 && ', '}
                                            <SeriesNamePart part={part} />
                                        </Fragment>
                                    ))}
                                </span>
                            )}
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

/** Side panel next to the chart: per-series totals, or the raw emissions
 * behind the chart with a link to the trace each one was recorded in. */
export function MetricsSamplesPanel(): JSX.Element {
    const { activeTab } = useValues(metricsSamplesLogic)
    const { setActiveTab } = useActions(metricsSamplesLogic)
    const { viewerClauses, activeClauseIndex } = useValues(metricsViewerLogic)
    const { setActiveClauseIndex } = useActions(metricsViewerLogic)
    const metricsViewerDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Metrics,
        AccessControlLevel.Viewer
    )

    return (
        <div className="border rounded p-2 overflow-y-auto">
            {/* Samples and the anomaly badge describe one series at a time; with several
                clauses this picks which one they follow. The Series tab always covers all series. */}
            {viewerClauses.length > 1 && (
                <div className="flex flex-wrap items-center gap-2 pb-1">
                    <span className="text-xs text-secondary">Samples follow series</span>
                    <LemonSegmentedButton
                        size="xsmall"
                        value={activeClauseIndex}
                        onChange={(index) => {
                            if (!metricsViewerDisabledReason) {
                                setActiveClauseIndex(index)
                            }
                        }}
                        options={viewerClauses.map((clause, index) => ({
                            value: index,
                            label: clause.name,
                            tooltip: clause.metricName.trim() || 'No metric picked',
                        }))}
                        data-attr="metrics-samples-panel-series-picker"
                    />
                </div>
            )}
            <LemonTabs<MetricsPanelTab>
                size="small"
                activeKey={activeTab}
                onChange={(tab) => {
                    if (!metricsViewerDisabledReason) {
                        setActiveTab(tab)
                    }
                }}
                tabs={[
                    {
                        key: 'aggregates',
                        label: 'Series',
                        content: <SeriesTab />,
                        'data-attr': 'metrics-samples-panel-tab-aggregates',
                        disabledReason: metricsViewerDisabledReason ?? undefined,
                    },
                    {
                        key: 'samples',
                        label: 'Samples',
                        content: <SamplesTab />,
                        'data-attr': 'metrics-samples-panel-tab-samples',
                        disabledReason: metricsViewerDisabledReason ?? undefined,
                    },
                ]}
            />
        </div>
    )
}
