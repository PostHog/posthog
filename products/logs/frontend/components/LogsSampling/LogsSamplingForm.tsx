import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton, LemonInput, LemonSegmentedButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { dataColorVars } from 'lib/colors'
import { Sparkline, SparklineReferenceLine, SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from './DropRuleFilterEditor'
import { RateLimitUnit, logsSamplingFormLogic, rateLimitAmountToKbPerSecond } from './logsSamplingFormLogic'

const RATE_LIMIT_UNIT_OPTIONS: { value: RateLimitUnit; label: string }[] = [
    { value: 'KB/s', label: 'KB/s' },
    { value: 'MB/s', label: 'MB/s' },
    { value: 'GB/s', label: 'GB/s' },
]

const ACTION_OPTIONS: { value: RuleTypeEnumApi; label: string }[] = [
    { value: RuleTypeEnumApi.PathDrop, label: 'Drop' },
    { value: RuleTypeEnumApi.RateLimit, label: 'Rate limit' },
]

const TOP_SERVICES_LIMIT = 10

interface SparklineSeriesData {
    labels: string[]
    series: SparklineTimeSeries[]
    total: number
    truncatedServiceCount: number
    /** Width of one bar/bucket in seconds; needed to translate a per-second rate limit into per-bucket units. */
    bucketSeconds: number
    /** Tallest stacked total across buckets; used to position the rate-limit reference line. */
    chartMax: number
}

type FilterPreviewPoint = { time: string; service: string; count: number; bytes_uncompressed?: number }

function buildSparklineSeries(points: FilterPreviewPoint[] | null, metric: 'count' | 'bytes'): SparklineSeriesData {
    if (!points || points.length === 0) {
        return { labels: [], series: [], total: 0, truncatedServiceCount: 0, bucketSeconds: 0, chartMax: 0 }
    }
    const timeOrder: string[] = []
    const seenTimes = new Set<string>()
    const byService: Record<string, Map<string, number>> = {}
    const serviceTotals = new Map<string, number>()
    const bucketTotals = new Map<string, number>()
    let total = 0
    for (const point of points) {
        if (!seenTimes.has(point.time)) {
            seenTimes.add(point.time)
            timeOrder.push(point.time)
        }
        const svc = point.service || 'unknown'
        const value = metric === 'bytes' ? (point.bytes_uncompressed ?? 0) : point.count
        const bucket = byService[svc] ?? (byService[svc] = new Map())
        bucket.set(point.time, (bucket.get(point.time) ?? 0) + value)
        serviceTotals.set(svc, (serviceTotals.get(svc) ?? 0) + value)
        bucketTotals.set(point.time, (bucketTotals.get(point.time) ?? 0) + value)
        total += value
    }
    const labels = timeOrder.map((t) => dayjs(t).format('D MMM HH:mm'))
    const rankedServices = Array.from(serviceTotals.entries()).sort(([, a], [, b]) => b - a)
    const topServices = rankedServices.slice(0, TOP_SERVICES_LIMIT)
    const otherServices = rankedServices.slice(TOP_SERVICES_LIMIT)
    const truncatedServiceCount = otherServices.length
    const series: SparklineTimeSeries[] = topServices.map(([service], index) => ({
        name: service,
        color: dataColorVars[index % dataColorVars.length],
        values: timeOrder.map((t) => byService[service]?.get(t) ?? 0),
    }))
    if (otherServices.length > 0) {
        // Roll up the long tail into a single "Others" series so the chart still adds up to total volume,
        // and the rate-limit reference line lines up against an honest stacked max.
        const othersValues = timeOrder.map((t) =>
            otherServices.reduce((sum, [service]) => sum + (byService[service]?.get(t) ?? 0), 0)
        )
        series.push({
            name: `Others (${otherServices.length} services)`,
            color: 'muted',
            values: othersValues,
        })
    }
    const bucketSeconds = timeOrder.length >= 2 ? dayjs(timeOrder[1]).diff(dayjs(timeOrder[0]), 'second') : 0
    const chartMax = Math.max(0, ...Array.from(bucketTotals.values()))
    return { labels, series, total, truncatedServiceCount, bucketSeconds, chartMax }
}

function formatBytes(bytes: number): string {
    if (bytes < 1000) {
        return `${bytes.toLocaleString()} B`
    }
    if (bytes < 1_000_000) {
        return `${(bytes / 1000).toFixed(1)} KB`
    }
    if (bytes < 1_000_000_000) {
        return `${(bytes / 1_000_000).toFixed(1)} MB`
    }
    return `${(bytes / 1_000_000_000).toFixed(2)} GB`
}

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, samplingFormErrors, filterPreview, filterPreviewLoading } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue, refreshFilterPreview } = useActions(logsSamplingFormLogic)

    const isRateLimit = samplingForm.rule_type === RuleTypeEnumApi.RateLimit
    const hasFilters = samplingForm.filter_group.values.length > 0

    const matchDescription = isRateLimit
        ? `Drop logs matching these filters above ${
              samplingForm.rate_limit_amount.trim()
                  ? `${samplingForm.rate_limit_amount.trim()} ${samplingForm.rate_limit_unit}`
                  : 'the configured rate limit'
          }.`
        : 'Drop logs matching these filters. Dropped lines are not stored — they will not appear in the UI, exports, or alerts. Already-dropped data cannot be recovered.'

    const previewMetric: 'count' | 'bytes' = isRateLimit ? 'bytes' : 'count'
    const { labels, series, total, bucketSeconds, chartMax } = useMemo(
        () => buildSparklineSeries(filterPreview, previewMetric),
        [filterPreview, previewMetric]
    )
    const formattedTotal = previewMetric === 'bytes' ? formatBytes(total) : `${total.toLocaleString()} logs`

    // Rate limit threshold projected onto the same y-axis units the chart uses (bytes/bucket).
    const rateLimitThresholdPerBucket = useMemo<number | null>(() => {
        if (!isRateLimit || bucketSeconds <= 0) {
            return null
        }
        const kbPerSecond = rateLimitAmountToKbPerSecond(samplingForm.rate_limit_amount, samplingForm.rate_limit_unit)
        if (!Number.isFinite(kbPerSecond) || kbPerSecond <= 0) {
            return null
        }
        // KB/s × 1000 = bytes/s, × bucket width in seconds = bytes/bucket.
        return kbPerSecond * 1000 * bucketSeconds
    }, [isRateLimit, bucketSeconds, samplingForm.rate_limit_amount, samplingForm.rate_limit_unit])

    const rateLimitReferenceLines = useMemo<SparklineReferenceLine[] | undefined>(() => {
        if (rateLimitThresholdPerBucket == null) {
            return undefined
        }
        return [
            {
                value: rateLimitThresholdPerBucket,
                color: 'danger',
                label: `Rate limit (${samplingForm.rate_limit_amount.trim()} ${samplingForm.rate_limit_unit})`,
                labelPosition: 'end',
            },
        ]
    }, [rateLimitThresholdPerBucket, samplingForm.rate_limit_amount, samplingForm.rate_limit_unit])

    const rateLimitAboveChart =
        rateLimitThresholdPerBucket != null && chartMax > 0 && rateLimitThresholdPerBucket > chartMax

    return (
        <div className="flex flex-col gap-4 max-w-3xl">
            <div className="flex flex-col gap-3">
                <LemonField.Pure label="Name" error={samplingFormErrors.name}>
                    <LemonInput
                        value={samplingForm.name}
                        onChange={(v) => setSamplingFormValue('name', v)}
                        placeholder="e.g. Drop noisy health checks"
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Enabled">
                    <LemonSwitch checked={samplingForm.enabled} onChange={(v) => setSamplingFormValue('enabled', v)} />
                </LemonField.Pure>
            </div>

            <SceneSection title="Action" titleSize="sm">
                <LemonField.Pure label="What to do when a log matches">
                    <LemonSegmentedButton
                        value={samplingForm.rule_type}
                        onChange={(v) => v && setSamplingFormValue('rule_type', v)}
                        options={ACTION_OPTIONS}
                        size="small"
                    />
                </LemonField.Pure>
                {isRateLimit && (
                    <LemonField.Pure
                        label="Rate limit"
                        help="Minimum 1 KB/s, maximum 1 GB/s. Fractional values allowed (e.g. 1.5 MB/s)."
                        error={samplingFormErrors.rate_limit_amount}
                    >
                        <div className="flex gap-2 items-center max-w-sm">
                            <LemonInput
                                value={samplingForm.rate_limit_amount}
                                onChange={(v) => setSamplingFormValue('rate_limit_amount', v)}
                                placeholder="e.g. 5"
                                inputMode="decimal"
                            />
                            <LemonSelect<RateLimitUnit>
                                value={samplingForm.rate_limit_unit}
                                onChange={(v) => v && setSamplingFormValue('rate_limit_unit', v)}
                                options={RATE_LIMIT_UNIT_OPTIONS}
                            />
                        </div>
                    </LemonField.Pure>
                )}
            </SceneSection>

            <SceneSection title="Match" titleSize="sm" description={matchDescription}>
                <DropRuleFilterEditor
                    filterGroup={samplingForm.filter_group}
                    onChange={(group) => setSamplingFormValue('filter_group', group)}
                />
                {/* filter_group is an object — kea-forms types only allow scalar field errors,
                    so this inline message mirrors what samplingFormSaveDisabledReason returns. */}
                {!hasFilters && <p className="text-danger text-xs mt-1 mb-0">Add at least one filter to match logs.</p>}
                <div className="mt-3 flex flex-col gap-1">
                    <div className="flex items-center justify-between text-xs text-muted">
                        <span>
                            Volume preview by service (last 24h, top {TOP_SERVICES_LIMIT}
                            {previewMetric === 'bytes' ? ', bytes' : ''})
                        </span>
                        {hasFilters && !filterPreviewLoading ? <span>{formattedTotal}</span> : null}
                    </div>
                    <div className="relative h-24 border border-border rounded-md bg-bg-light px-2 py-1">
                        {!hasFilters ? (
                            <div className="h-full flex items-center justify-center text-muted text-xs">
                                Add a filter above to preview matching log volume
                            </div>
                        ) : filterPreviewLoading ? (
                            <Sparkline
                                data={[]}
                                labels={[]}
                                loading
                                className="w-full h-full"
                                maximumIndicator={false}
                            />
                        ) : !filterPreview ? (
                            <div className="h-full flex flex-col gap-1 items-center justify-center text-muted text-xs">
                                <span>Couldn't load the volume preview.</span>
                                <LemonButton size="xsmall" type="secondary" onClick={refreshFilterPreview}>
                                    Retry
                                </LemonButton>
                            </div>
                        ) : series.length === 0 ? (
                            <div className="h-full flex items-center justify-center text-muted text-xs">
                                No logs match these filters in the last 24h
                            </div>
                        ) : (
                            <Sparkline
                                data={series}
                                labels={labels}
                                className="w-full h-full"
                                maximumIndicator={false}
                                referenceLines={rateLimitReferenceLines}
                                renderTooltipValue={previewMetric === 'bytes' ? formatBytes : undefined}
                            />
                        )}
                    </div>
                    {isRateLimit && rateLimitAboveChart ? (
                        <div className="text-xs text-muted">
                            Rate limit is above the current peak — no logs would be dropped in the previewed window.
                        </div>
                    ) : null}
                </div>
            </SceneSection>
        </div>
    )
}
