import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInput, LemonSegmentedButton, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { dataColorVars } from 'lib/colors'
import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from './DropRuleFilterEditor'
import { RateLimitUnit, logsSamplingFormLogic } from './logsSamplingFormLogic'

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
}

function buildSparklineSeries(
    points: { time: string; service_name: string; count: number }[] | null
): SparklineSeriesData {
    if (!points || points.length === 0) {
        return { labels: [], series: [], total: 0, truncatedServiceCount: 0 }
    }
    const timeOrder: string[] = []
    const seenTimes = new Set<string>()
    const byService: Record<string, Map<string, number>> = {}
    const serviceTotals = new Map<string, number>()
    let total = 0
    for (const point of points) {
        if (!seenTimes.has(point.time)) {
            seenTimes.add(point.time)
            timeOrder.push(point.time)
        }
        const svc = point.service_name || 'unknown'
        const bucket = byService[svc] ?? (byService[svc] = new Map())
        bucket.set(point.time, (bucket.get(point.time) ?? 0) + point.count)
        serviceTotals.set(svc, (serviceTotals.get(svc) ?? 0) + point.count)
        total += point.count
    }
    const labels = timeOrder.map((t) => dayjs(t).format('D MMM HH:mm'))
    const rankedServices = Array.from(serviceTotals.entries()).sort(([, a], [, b]) => b - a)
    const topServices = rankedServices.slice(0, TOP_SERVICES_LIMIT)
    const truncatedServiceCount = Math.max(0, rankedServices.length - topServices.length)
    const series = topServices.map(([service], index) => ({
        name: service,
        color: dataColorVars[index % dataColorVars.length],
        values: timeOrder.map((t) => byService[service]?.get(t) ?? 0),
    }))
    return { labels, series, total, truncatedServiceCount }
}

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, samplingFormErrors, filterPreview, filterPreviewLoading } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isRateLimit = samplingForm.rule_type === RuleTypeEnumApi.RateLimit
    const hasFilters = samplingForm.filter_group.values.length > 0

    const matchDescription = isRateLimit
        ? `Drop logs matching these filters above ${
              samplingForm.rate_limit_amount.trim()
                  ? `${samplingForm.rate_limit_amount.trim()} ${samplingForm.rate_limit_unit}`
                  : 'the configured rate limit'
          }.`
        : 'Drop logs matching these filters. Dropped lines are not stored — they will not appear in the UI, exports, or alerts. Already-dropped data cannot be recovered.'

    const { labels, series, total, truncatedServiceCount } = useMemo(
        () => buildSparklineSeries(filterPreview),
        [filterPreview]
    )

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
                <LemonField.Pure error={samplingFormErrors.filter_group as string | undefined}>
                    <DropRuleFilterEditor
                        filterGroup={samplingForm.filter_group}
                        onChange={(group) => setSamplingFormValue('filter_group', group)}
                    />
                </LemonField.Pure>
                <div className="mt-3 flex flex-col gap-1">
                    <div className="flex items-center justify-between text-xs text-muted">
                        <span>
                            Volume preview by service (last 24h, top {TOP_SERVICES_LIMIT})
                            {truncatedServiceCount > 0 ? ` — ${truncatedServiceCount} more not shown` : ''}
                        </span>
                        {hasFilters && !filterPreviewLoading ? (
                            <span>{total.toLocaleString()} matching logs</span>
                        ) : null}
                    </div>
                    <div className="relative h-24 border border-border rounded-md bg-bg-light px-2 py-1">
                        {!hasFilters ? (
                            <div className="h-full flex items-center justify-center text-muted text-xs">
                                Add a filter above to preview matching log volume
                            </div>
                        ) : filterPreviewLoading || !filterPreview ? (
                            <Sparkline
                                data={[]}
                                labels={[]}
                                loading
                                className="w-full h-full"
                                maximumIndicator={false}
                            />
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
                            />
                        )}
                    </div>
                </div>
            </SceneSection>
        </div>
    )
}
