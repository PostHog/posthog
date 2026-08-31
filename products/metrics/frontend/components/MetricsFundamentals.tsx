import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonCollapse, LemonInput, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import type { _MetricBucketDecompositionApi, _MetricSeriesBreakdownApi } from '../generated/api.schemas'
import { metricsFundamentalsLogic } from './metricsFundamentalsLogic'
import type { MetricAggregation } from './metricsViewerLogic'

// Each rule states what should happen, then the formula, then a worked example
// small enough to check by eye. Someone who has never thought about metric
// aggregation should be able to read one card and know what to look for.
const RULES: { key: string; title: string; should: string; formula: string; example: string }[] = [
    {
        key: 'two-axes',
        title: 'A bucket holds series, not numbers',
        should: 'Every value is reduced twice. First each series is collapsed on its own, then those results are combined across series. Doing it in one step counts a series once per scrape, so the answer follows how often you collect rather than what you measured.',
        formula: 'value = combine(over each series: collapse(its samples))',
        example:
            'Two pods, three scrapes each, one bucket. That is 6 samples but only 2 series. A total should add 2 numbers, not 6.',
    },
    {
        key: 'typing',
        title: 'The metric type decides how a series collapses',
        should: 'A gauge sample is a fresh reading, so the newest one wins. A cumulative counter is an odometer, so you subtract consecutive readings. A delta counter reports an increment each time, so you add them up. One rule applied to all three is wrong for two of them.',
        formula: 'gauge: last  ·  cumulative counter: sum of diffs  ·  delta counter: sum',
        example:
            'A counter reading 100, 120, 5, 25 rose by 45. The drop to 5 is a restart, so 5 is itself an increase.',
    },
    {
        key: 'scrape-rate',
        title: 'Collecting more often must not change the answer',
        should: 'Sending the same reading twice is one observation delivered twice. If a value moves when a scrape is duplicated, dropped, or a bucket is still filling, the reduction is counting rows instead of series.',
        formula: 'value(samples) == value(samples delivered twice)',
        example:
            'A gauge scraped 10 times a bucket that reads 10x too high is the classic case. The multiplier moves with the scrape rate, so the chart jumps for no real reason.',
    },
    {
        key: 'staleness',
        title: 'A series that goes quiet is not a zero',
        should: 'A series that reports in one bucket and not the next has not dropped to zero, it just has not been heard from. Totals over sparsely reported metrics swing on how many series happened to report, which reads as a real change but is not one.',
        formula: 'absent series should carry forward or drop out, never count as 0',
        example:
            'A total across 300 series where only 5 report each minute swings by millions between buckets purely on who reported. The check above cannot catch this one. It reads a single bucket, so a series that never reported is invisible to it. Compare neighbouring buckets by hand.',
    },
    {
        key: 'ordering',
        title: 'Percentiles and rates do not survive being averaged',
        should: 'A percentile of percentiles is not a percentile, and a rate of summed counters misreads restarts. Rates reduce inside each series first, then combine. Percentiles go the other way and read every reading in the bucket, because collapsing a series to one number throws away the tail the percentile is asking about. The tradeoff is that a series collected more often contributes more readings to that tail.',
        formula: 'sum(rate(x)), never rate(sum(x))',
        example:
            'Host A serves 1,000 requests at p95 of 1ms, host B serves 10 at 2,000ms. Averaging the two p95s gives about 1,000ms. The real combined p95 is about 1ms.',
    },
]

// These describe the reduction the check itself applied, which is only also
// what the chart did when the two agree. The wording says so either way.
const TEMPORAL_REDUCER_COPY: Record<string, string> = {
    last: 'took each series latest reading',
    avg_over_time: 'averaged each series readings over the bucket',
    sum_over_time: 'added up each series increments',
    increase: 'measured how much each series rose',
    pooled_samples: 'used every reading rather than one value per series',
    none: 'did not reduce per series, so every raw sample counted',
}

const SPATIAL_REDUCER_COPY: Record<string, string> = {
    sum: 'added the series together',
    avg: 'averaged across series',
    min: 'took the smallest series',
    max: 'took the largest series',
    quantile: 'took a percentile across series',
    count_series: 'counted how many series reported',
}

const AGGREGATION_OPTIONS: { value: MetricAggregation; label: string }[] = [
    { value: 'sum', label: 'Sum' },
    { value: 'avg', label: 'Average' },
    { value: 'count', label: 'Count' },
    { value: 'min', label: 'Min' },
    { value: 'max', label: 'Max' },
    { value: 'p95', label: 'p95' },
    { value: 'rate', label: 'Rate (/s)' },
    { value: 'increase', label: 'Increase' },
]

// Float reductions land on values like 79.33333333333333, which are unreadable
// next to each other and imply a precision the comparison does not use.
const formatValue = (value: number | null): string =>
    value === null ? 'no value' : Number(value.toPrecision(10)).toLocaleString('en-US', { maximumFractionDigits: 4 })

const SeriesRow = ({ series }: { series: _MetricSeriesBreakdownApi }): JSX.Element => {
    const labelText =
        Object.entries(series.labels)
            .map(([key, value]) => `${key}=${value}`)
            .join(' ') || 'no labels'

    return (
        <div className="flex flex-col gap-1 py-2 border-b last:border-b-0">
            <div className="flex items-baseline justify-between gap-2">
                <span className="font-mono text-xs truncate">
                    {series.service_name} {labelText}
                </span>
                <span className="font-semibold shrink-0">
                    {series.value === null ? `${series.sample_count} readings` : formatValue(series.value)}
                </span>
            </div>
            <div className="font-mono text-xs text-muted">
                {series.samples.map((sample) => sample.value).join(', ')}
                {series.samples_truncated && ` and ${series.sample_count - series.samples.length} more`}
            </div>
        </div>
    )
}

const Decomposition = ({ decomposition }: { decomposition: _MetricBucketDecompositionApi }): JSX.Element => {
    const temporal = TEMPORAL_REDUCER_COPY[decomposition.temporal_reducer] ?? decomposition.temporal_reducer
    const spatial = SPATIAL_REDUCER_COPY[decomposition.spatial_reducer] ?? decomposition.spatial_reducer

    return (
        <div className="flex flex-col gap-3">
            <LemonBanner type={decomposition.agrees === null ? 'warning' : decomposition.agrees ? 'success' : 'error'}>
                {decomposition.agrees === null ? (
                    <>
                        This bucket holds more raw samples than the check reads, so the recomputed value covers only
                        part of the data and proves nothing about the chart's {formatValue(decomposition.actual_value)}.
                        Narrow with a filter and check again.
                    </>
                ) : decomposition.agrees ? (
                    <>
                        The chart shows {formatValue(decomposition.actual_value)} for this bucket, and recomputing it
                        from the raw samples gives the same number.
                    </>
                ) : (
                    <>
                        The chart shows {formatValue(decomposition.actual_value)} for this bucket, but recomputing it
                        from the raw samples gives {formatValue(decomposition.reference_value)}. One of the two is
                        wrong. The series below show what the data actually contains.
                    </>
                )}
            </LemonBanner>

            <div className="flex flex-wrap gap-1">
                <LemonTag>{decomposition.metric_type || 'unknown type'}</LemonTag>
                {decomposition.temporality && <LemonTag>{decomposition.temporality}</LemonTag>}
                <LemonTag>{decomposition.series_count} series</LemonTag>
                <LemonTag>{decomposition.sample_count} samples</LemonTag>
            </div>

            <p className="mb-0">
                To get {formatValue(decomposition.reference_value)}, the check {temporal}, then {spatial}.
                {decomposition.aggregation === 'rate' &&
                    ' The result is divided by the bucket length, so it is per second.'}
                {decomposition.agrees === false && ' The chart reached its number a different way.'}
            </p>

            <div>
                <h4>Series in this bucket</h4>
                {decomposition.series.map((series, index) => (
                    <SeriesRow key={index} series={series} />
                ))}
                {decomposition.series_truncated && (
                    <p className="text-muted mt-2 mb-0">
                        Showing the {decomposition.series.length} largest of {decomposition.series_count} series. The
                        totals above cover all of them.
                    </p>
                )}
            </div>
        </div>
    )
}

export function MetricsFundamentals(): JSX.Element {
    const { metricName, aggregation, checkResult, checkResultLoading } = useValues(metricsFundamentalsLogic)
    const { setMetricName, setAggregation, runCheck } = useActions(metricsFundamentalsLogic)

    return (
        <div className="flex flex-col gap-4 overflow-y-auto">
            <p className="mb-0">
                What a metrics chart shows depends on how its numbers were combined, and a wrong combination still looks
                like a normal chart. This page explains the rules a correct chart follows, then checks a real point
                against them.
            </p>

            <div>
                <h3>Check a point</h3>
                <p className="text-muted">
                    Pick a metric and we take its most recent complete 5 minute bucket apart. The value is recomputed
                    from the raw samples and compared against what the chart would draw.
                </p>
                <div className="flex flex-wrap items-center gap-2">
                    <LemonInput
                        value={metricName}
                        onChange={setMetricName}
                        onPressEnter={() => runCheck()}
                        placeholder="Metric name"
                        className="w-80"
                    />
                    <LemonSelect<MetricAggregation>
                        value={aggregation}
                        onChange={setAggregation}
                        options={AGGREGATION_OPTIONS}
                    />
                    <LemonButton
                        type="primary"
                        onClick={() => runCheck()}
                        loading={checkResultLoading}
                        disabledReason={!metricName ? 'Enter a metric name' : undefined}
                    >
                        Check
                    </LemonButton>
                </div>
            </div>

            {checkResult && !checkResultLoading && <Decomposition decomposition={checkResult.decomposition} />}

            <div>
                <h3>The rules</h3>
                <LemonCollapse
                    multiple
                    panels={RULES.map((rule) => ({
                        key: rule.key,
                        header: rule.title,
                        content: (
                            <div className="flex flex-col gap-2">
                                <p className="mb-0">{rule.should}</p>
                                <code className="text-xs">{rule.formula}</code>
                                <p className="text-muted mb-0">{rule.example}</p>
                            </div>
                        ),
                    }))}
                />
            </div>
        </div>
    )
}
