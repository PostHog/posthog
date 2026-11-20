import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonTable, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import { SUMMARY_LIMIT, metricsSummaryLogic } from './metricsSummaryLogic'

export const MetricsSummaryTable = (): JSX.Element => {
    const { filteredMetrics, metrics, metricsLoading, metricsFailed, search, catalogTruncated } =
        useValues(metricsSummaryLogic)
    const { setSearch, viewMetric, loadMetrics } = useActions(metricsSummaryLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <h3 className="mb-0">Metrics</h3>
                <LemonInput
                    type="search"
                    placeholder="Filter metrics"
                    value={search}
                    onChange={setSearch}
                    size="small"
                    data-attr="metrics-summary-filter"
                />
            </div>
            {metricsFailed ? (
                // Outside the table: a failed search can leave earlier rows on screen, which hides the empty state.
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadMetrics() }}>
                    Couldn't load metrics.
                </LemonBanner>
            ) : null}
            <LemonTable
                dataSource={filteredMetrics}
                loading={metricsLoading && metrics.length === 0}
                rowKey="name"
                pagination={{ pageSize: 50 }}
                defaultSorting={{ columnKey: 'series_count', order: -1 }}
                emptyState={
                    metricsFailed
                        ? "Couldn't load metrics."
                        : search
                          ? 'No metrics match this filter.'
                          : 'No metrics have arrived in the last 24 hours.'
                }
                footer={
                    catalogTruncated && metrics.length >= SUMMARY_LIMIT ? (
                        <div className="text-xs text-secondary p-2">
                            Showing the first {SUMMARY_LIMIT} metrics. Filter to narrow the list.
                        </div>
                    ) : undefined
                }
                columns={[
                    {
                        title: 'Metric',
                        key: 'name',
                        render: (_, metric) => (
                            <Link
                                data-attr="metrics-summary-metric-link"
                                title="Open this metric in the viewer"
                                onClick={() => viewMetric(metric.name)}
                            >
                                {metric.name}
                            </Link>
                        ),
                        sorter: (a, b) => a.name.localeCompare(b.name),
                    },
                    {
                        title: 'Type',
                        key: 'metric_type',
                        render: (_, metric) => metric.metric_type || '-',
                        sorter: (a, b) => a.metric_type.localeCompare(b.metric_type),
                    },
                    {
                        title: 'Unit',
                        key: 'unit',
                        render: (_, metric) => metric.unit || '-',
                        sorter: (a, b) => (a.unit ?? '').localeCompare(b.unit ?? ''),
                    },
                    {
                        title: 'Tags',
                        key: 'tag_key_count',
                        align: 'right',
                        tooltip: 'Distinct attribute keys on the metric in the last 24 hours',
                        render: (_, metric) => humanFriendlyNumber(metric.tag_key_count ?? 0),
                        sorter: (a, b) => (a.tag_key_count ?? 0) - (b.tag_key_count ?? 0),
                    },
                    {
                        title: 'Series',
                        key: 'series_count',
                        align: 'right',
                        tooltip: 'Approximate number of distinct label sets in the last 24 hours',
                        render: (_, metric) => humanFriendlyNumber(metric.series_count ?? 0),
                        sorter: (a, b) => (a.series_count ?? 0) - (b.series_count ?? 0),
                    },
                    {
                        title: 'Last seen',
                        key: 'last_seen',
                        render: (_, metric) => (metric.last_seen ? <TZLabel time={metric.last_seen} /> : '-'),
                        sorter: (a, b) => (a.last_seen ?? '').localeCompare(b.last_seen ?? ''),
                    },
                ]}
            />
        </div>
    )
}
