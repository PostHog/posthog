import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Fragment, useEffect, useRef, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton, LemonTable, LemonTabs, Link, Tooltip } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { TZLabel } from 'lib/components/TZLabel'
import { traceUrl } from 'lib/components/ViewTraceButton/traceUrl'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { humanFriendlyLargeNumber, humanFriendlyNumber } from 'lib/utils/numbers'
import { teamLogic } from 'scenes/teamLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LogRowScrollButtons } from 'products/logs/frontend/components/VirtualizedLogsList/LogRowScrollButtons'
import { useOpenTraceDialog } from 'products/tracing/frontend/components/TraceDialog/useOpenTraceDialog'

import { type MetricsSeriesRow, type MetricsPanelTab, metricsSamplesLogic } from './metricsSamplesLogic'
import { metricsUsageTrackingLogic } from './metricsUsageTrackingLogic'
import { metricsViewerLogic } from './metricsViewerLogic'
import { SampleAttributes } from './SampleAttributes'

function SamplesTab(): JSX.Element {
    const { samples, samplesLoading } = useValues(metricsSamplesLogic)
    const { hasMetricName } = useValues(metricsViewerLogic)
    const { timezone } = useValues(teamLogic)
    const { sampleRowExpanded, tracePivotClicked } = useActions(metricsUsageTrackingLogic)
    const openTraceDialog = useOpenTraceDialog()
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
                                    onClick={(event) => {
                                        tracePivotClicked(sample)
                                        openTraceDialog(
                                            event,
                                            {
                                                traceId: sample.trace_id,
                                                spanId: sample.span_id || null,
                                                ts: sample.timestamp,
                                            },
                                            { entryPoint: 'metric_sample' }
                                        )
                                    }}
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

const SCROLL_INTERVAL_MS = 16
const SCROLL_STEP_PX = 8

/** Scrolls long labels sideways, with hold-to-scroll buttons on hover as in the logs table. */
function HorizontalScroll({ children, className }: { children: React.ReactNode; className?: string }): JSX.Element {
    const scrollRef = useRef<HTMLDivElement>(null)
    const contentRef = useRef<HTMLDivElement>(null)
    const intervalRef = useRef<number | null>(null)
    const [canScroll, setCanScroll] = useState(false)

    const stopScrolling = (): void => {
        if (intervalRef.current !== null) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
        }
    }
    const startScrolling = (direction: 'left' | 'right'): void => {
        stopScrolling()
        const step = (): void =>
            scrollRef.current?.scrollBy({ left: direction === 'left' ? -SCROLL_STEP_PX : SCROLL_STEP_PX })
        step()
        intervalRef.current = window.setInterval(step, SCROLL_INTERVAL_MS)
    }
    useEffect(() => stopScrolling, [])

    return (
        <div
            className={clsx('relative min-w-0 group/scroll', className)}
            onMouseEnter={() => {
                const element = scrollRef.current
                const content = contentRef.current
                setCanScroll(!!element && !!content && content.offsetWidth > element.clientWidth)
            }}
        >
            <div ref={scrollRef} className="overflow-x-auto hide-scrollbar whitespace-nowrap">
                <div className="flex w-max">
                    <div ref={contentRef}>{children}</div>
                    {/* Lets the end of the text scroll clear of the buttons. */}
                    {canScroll && <div className="w-20 shrink-0" />}
                </div>
            </div>
            {canScroll && (
                <LogRowScrollButtons
                    onStartScrolling={startScrolling}
                    onStopScrolling={stopScrolling}
                    className="group-hover/scroll:opacity-100"
                />
            )}
        </div>
    )
}

function LabelValue({ value }: { value: string }): JSX.Element {
    return value ? <>{value}</> : <span className="text-tertiary italic">(empty)</span>
}

/** Compact so the series column keeps its width. The tooltip has the exact value. */
function SeriesValue({ value }: { value: number }): JSX.Element {
    return (
        <Tooltip title={humanFriendlyNumber(value, 2)}>
            <span className="font-mono">{humanFriendlyLargeNumber(value)}</span>
        </Tooltip>
    )
}

function SeriesTab(): JSX.Element {
    const { seriesRows } = useValues(metricsSamplesLogic)
    const { queryLoading, hasMetricName } = useValues(metricsViewerLogic)
    const { seriesRowExpanded } = useActions(metricsUsageTrackingLogic)
    const [expandedNames, setExpandedNames] = useState<string[]>([])
    // A row can lose its distinct labels after a filter change while its name stays in expandedNames.
    const isRowExpanded = (row: MetricsSeriesRow): boolean => row.labels.length > 0 && expandedNames.includes(row.name)

    return (
        <LemonTable
            dataSource={seriesRows}
            loading={queryLoading}
            size="small"
            rowKey={(row: MetricsSeriesRow) => row.name}
            emptyState={hasMetricName ? 'No series in the selected range.' : 'Pick a metric to see its series.'}
            rowClassName={(row) => (isRowExpanded(row) ? '[&>td]:align-top' : null)}
            columns={[
                {
                    key: 'toggle',
                    width: 0,
                    render: (_, row) => {
                        if (!row.labels.length) {
                            return null
                        }
                        const isExpanded = isRowExpanded(row)
                        return (
                            <LemonButton
                                noPadding
                                active={isExpanded}
                                icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                                title={isExpanded ? 'Show less' : 'Show the labels of this series'}
                                onClick={() => {
                                    if (isExpanded) {
                                        setExpandedNames(expandedNames.filter((name) => name !== row.name))
                                    } else {
                                        setExpandedNames([...expandedNames, row.name])
                                        seriesRowExpanded()
                                    }
                                }}
                                data-attr="metrics-series-row-toggle"
                            />
                        )
                    },
                },
                {
                    title: 'Series',
                    key: 'series',
                    width: '100%',
                    render: (_, row) => {
                        const isExpanded = isRowExpanded(row)
                        return (
                            <span className={clsx('flex gap-1.5', isExpanded ? 'items-start' : 'items-center')}>
                                <span
                                    className={clsx('w-2 h-2 rounded-full shrink-0', isExpanded && 'mt-1.5')}
                                    // Dynamic per-series colour can't be a Tailwind class.
                                    style={{ backgroundColor: getColorVar(row.color) }}
                                />
                                <HorizontalScroll className="w-0 flex-1">
                                    {isExpanded ? (
                                        <div className="flex flex-col gap-1">
                                            {row.labels.map(([key, value], index) => (
                                                <span key={key}>
                                                    {index === 0 && row.prefix}
                                                    <span className="text-tertiary">{key}=</span>
                                                    <LabelValue value={value} />
                                                </span>
                                            ))}
                                        </div>
                                    ) : (
                                        <span title={row.name}>
                                            {row.labels.length
                                                ? [
                                                      row.prefix,
                                                      ...row.labels.map(([key, value], index) => (
                                                          <Fragment key={key}>
                                                              {index > 0 && <span className="text-tertiary"> · </span>}
                                                              <LabelValue value={value} />
                                                          </Fragment>
                                                      )),
                                                  ]
                                                : row.fallbackName}
                                        </span>
                                    )}
                                </HorizontalScroll>
                            </span>
                        )
                    },
                },
                {
                    title: 'Latest',
                    key: 'latest',
                    align: 'right',
                    render: (_, row) => <SeriesValue value={row.latest} />,
                },
                {
                    title: 'Total',
                    key: 'total',
                    align: 'right',
                    render: (_, row) => <SeriesValue value={row.total} />,
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
