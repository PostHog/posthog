import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonInput, LemonSegmentedButton, LemonSwitch } from '@posthog/lemon-ui'

import { Sparkline, SparklineTimeSeries } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { RuleTypeEnumApi } from 'products/logs/frontend/generated/api.schemas'

import { DropRuleFilterEditor } from './DropRuleFilterEditor'
import { logsSamplingFormLogic } from './logsSamplingFormLogic'

const ACTION_OPTIONS: { value: RuleTypeEnumApi; label: string }[] = [
    { value: RuleTypeEnumApi.PathDrop, label: 'Drop' },
    { value: RuleTypeEnumApi.RateLimit, label: 'Rate limit' },
]

const SEVERITY_COLORS: Record<string, string> = {
    fatal: 'danger-dark',
    error: 'danger',
    warn: 'warning',
    info: 'brand-blue',
    debug: 'muted',
    trace: 'muted-alt',
}

interface SparklineSeriesData {
    labels: string[]
    series: SparklineTimeSeries[]
    total: number
}

function buildSparklineSeries(points: { time: string; severity: string; count: number }[] | null): SparklineSeriesData {
    if (!points || points.length === 0) {
        return { labels: [], series: [], total: 0 }
    }
    const timeOrder: string[] = []
    const seenTimes = new Set<string>()
    const bySeverity: Record<string, Map<string, number>> = {}
    let total = 0
    for (const point of points) {
        if (!seenTimes.has(point.time)) {
            seenTimes.add(point.time)
            timeOrder.push(point.time)
        }
        const sev = point.severity || 'info'
        const bucket = bySeverity[sev] ?? (bySeverity[sev] = new Map())
        bucket.set(point.time, (bucket.get(point.time) ?? 0) + point.count)
        total += point.count
    }
    const labels = timeOrder.map((t) => dayjs(t).format('D MMM HH:mm'))
    const series = Object.entries(bySeverity)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([severity, bucket]) => ({
            name: severity,
            color: SEVERITY_COLORS[severity] ?? 'muted',
            values: timeOrder.map((t) => bucket.get(t) ?? 0),
        }))
    return { labels, series, total }
}

export function LogsSamplingForm(): JSX.Element {
    const { samplingForm, samplingFormErrors, filterPreview, filterPreviewLoading } = useValues(logsSamplingFormLogic)
    const { setSamplingFormValue } = useActions(logsSamplingFormLogic)

    const isRateLimit = samplingForm.rule_type === RuleTypeEnumApi.RateLimit
    const hasFilters = samplingForm.filter_group.values.length > 0

    const { labels, series, total } = useMemo(() => buildSparklineSeries(filterPreview), [filterPreview])

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

            <SceneSection
                title="Match"
                titleSize="sm"
                description="Drop logs matching these filters. Dropped lines are not stored — they will not appear in the UI, exports, or alerts. Already-dropped data cannot be recovered."
            >
                <LemonField.Pure error={samplingFormErrors.filter_group as string | undefined}>
                    <DropRuleFilterEditor
                        filterGroup={samplingForm.filter_group}
                        onChange={(group) => setSamplingFormValue('filter_group', group)}
                    />
                </LemonField.Pure>
                <div className="mt-3 flex flex-col gap-1">
                    <div className="flex items-center justify-between text-xs text-muted">
                        <span>Volume preview (last 24h)</span>
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
                        label="Sustained limit (kilobytes per second)"
                        help="Whole number from 1 to 1,000,000."
                        error={samplingFormErrors.rate_limit_logs_per_second}
                    >
                        <LemonInput
                            value={samplingForm.rate_limit_logs_per_second}
                            onChange={(v) => setSamplingFormValue('rate_limit_logs_per_second', v)}
                            placeholder="e.g. 5000"
                            className="max-w-xs"
                        />
                    </LemonField.Pure>
                )}
            </SceneSection>
        </div>
    )
}
