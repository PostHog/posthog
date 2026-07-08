import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonInput, LemonInputSelect, LemonSelect, LemonTable, Link } from '@posthog/lemon-ui'
import { traceUrl } from '@posthog/products-tracing/frontend/traceLinks'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TZLabel } from 'lib/components/TZLabel'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { _MetricEventSampleApi } from 'products/metrics/frontend/generated/api.schemas'

import { MetricNameFilter } from './MetricNameFilter'
import { MetricSampleAttributes } from './MetricSampleAttributes'
import { METRICS_DATE_OPTIONS } from './metricsDates'
import { metricsSamplesLogic } from './metricsSamplesLogic'

const LIMIT_OPTIONS = [100, 250, 500, 1000].map((value) => ({ value, label: `${value} samples` }))

const ATTRIBUTE_PREVIEW_COUNT = 3

function attributePreview(attributes: Record<string, string>): string {
    const entries = Object.entries(attributes)
    const preview = entries
        .slice(0, ATTRIBUTE_PREVIEW_COUNT)
        .map(([key, value]) => `${key}=${value}`)
        .join(', ')
    return entries.length > ATTRIBUTE_PREVIEW_COUNT ? `${preview}, …` : preview
}

export function MetricsSamples(): JSX.Element {
    const {
        metricName,
        dateFrom,
        dateTo,
        traceId,
        limit,
        serviceFilter,
        serviceOptions,
        filteredSamples,
        samplesLoading,
    } = useValues(metricsSamplesLogic)
    const { setMetricName, setDateFrom, setDateTo, setTraceId, setLimit, setServiceFilter } =
        useActions(metricsSamplesLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
                <MetricNameFilter value={metricName} onChange={setMetricName} />
                <DateFilter
                    size="small"
                    dateFrom={dateFrom}
                    dateTo={dateTo}
                    dateOptions={METRICS_DATE_OPTIONS}
                    onChange={(changedDateFrom, changedDateTo) => {
                        setDateFrom(changedDateFrom)
                        setDateTo(changedDateTo)
                    }}
                    allowTimePrecision
                    allowFixedRangeWithTime
                    allowedRollingDateOptions={['minutes', 'hours', 'days', 'weeks']}
                    use24HourFormat
                />
                <LemonInputSelect
                    mode="multiple"
                    size="small"
                    value={serviceFilter}
                    onChange={setServiceFilter}
                    options={serviceOptions.map((service) => ({ key: service, label: service }))}
                    placeholder="Filter by service…"
                    className="min-w-[12rem]"
                />
                <LemonInput
                    size="small"
                    value={traceId}
                    onChange={setTraceId}
                    placeholder="Filter by trace ID…"
                    className="min-w-[14rem] font-mono"
                    allowClear
                />
                <LemonSelect size="small" value={limit} options={LIMIT_OPTIONS} onChange={setLimit} />
            </div>
            {!metricName.trim() ? (
                <div className="border rounded p-8 flex items-center justify-center text-secondary text-sm">
                    Pick a metric to see its raw emissions.
                </div>
            ) : (
                <LemonTable<_MetricEventSampleApi>
                    dataSource={filteredSamples}
                    loading={samplesLoading}
                    rowKey={(sample) => `${sample.timestamp}/${sample.span_id}/${sample.value}`}
                    columns={[
                        {
                            title: 'Timestamp',
                            key: 'timestamp',
                            width: 0,
                            render: (_, sample) => (
                                <span className="whitespace-nowrap">
                                    <TZLabel time={sample.timestamp} timestampStyle="absolute" />
                                </span>
                            ),
                        },
                        {
                            title: 'Value',
                            key: 'value',
                            align: 'right',
                            width: 0,
                            render: (_, sample) => (
                                <span className="font-mono whitespace-nowrap">
                                    {humanFriendlyNumber(sample.value)}
                                    {sample.unit ? ` ${sample.unit}` : ''}
                                </span>
                            ),
                        },
                        {
                            title: 'Count',
                            key: 'count',
                            align: 'right',
                            width: 0,
                            render: (_, sample) => (
                                <span className="font-mono">{humanFriendlyNumber(sample.count)}</span>
                            ),
                        },
                        {
                            title: 'Service',
                            key: 'service',
                            width: 0,
                            render: (_, sample) => (
                                <span className="whitespace-nowrap">{sample.service_name || '—'}</span>
                            ),
                        },
                        {
                            title: 'Attributes',
                            key: 'attributes',
                            render: (_, sample) => (
                                <span className="font-mono text-xs text-muted">
                                    {attributePreview(sample.attributes)}
                                </span>
                            ),
                        },
                        {
                            title: 'Trace',
                            key: 'trace',
                            width: 0,
                            render: (_, sample) =>
                                sample.trace_id ? (
                                    <div className="flex items-center gap-1 whitespace-nowrap">
                                        <Link
                                            to={traceUrl({
                                                traceId: sample.trace_id,
                                                spanId: sample.span_id || undefined,
                                                ts: sample.timestamp,
                                            })}
                                            className="font-mono text-xs"
                                        >
                                            {sample.trace_id.slice(0, 8)}…
                                        </Link>
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconFilter />}
                                            tooltip="Only show emissions on this trace"
                                            onClick={() => setTraceId(sample.trace_id)}
                                        />
                                    </div>
                                ) : (
                                    <span className="text-muted">—</span>
                                ),
                        },
                    ]}
                    expandable={{
                        noIndent: true,
                        expandedRowRender: (sample) => (
                            <div className="flex flex-col gap-2 p-2">
                                <MetricSampleAttributes title="Attributes" attributes={sample.attributes} />
                                <MetricSampleAttributes
                                    title="Resource attributes"
                                    attributes={sample.resource_attributes}
                                />
                                {Object.keys(sample.attributes).length === 0 &&
                                    Object.keys(sample.resource_attributes).length === 0 && (
                                        <span className="text-secondary text-sm">This emission has no attributes.</span>
                                    )}
                            </div>
                        ),
                    }}
                    emptyState="No emissions for this metric in the selected range."
                />
            )}
        </div>
    )
}
