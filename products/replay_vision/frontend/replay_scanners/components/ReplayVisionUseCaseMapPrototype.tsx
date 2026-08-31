import { useState } from 'react'

import { IconPlay, IconPlus, IconSparkles, IconTrending } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'
import { ReferenceLine, type Series, TimeSeriesBarChart, type TimeSeriesBarChartConfig } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { IconTrendingDown } from 'lib/lemon-ui/icons'

export type UseCaseChangeDirection = 'new' | 'growing' | 'fading'

export interface UseCaseEvidence {
    recordingId: string
    summary: string
    timestampLabel: string
    timestampMs: number
    confidence: number
}

export interface UseCaseChange {
    key: string
    label: string
    direction: UseCaseChangeDirection
    source: 'configured' | 'freeform'
    currentShare: number
    percentagePointChange: number | null
    currentSessionCount: number
    firstObservedAt?: string
    firstObservedLabel?: string
    evidence: UseCaseEvidence[]
}

export interface ReplayVisionUseCaseMapPrototypeProps {
    productName: string
    dateLabels: string[]
    series: Series[]
    changes: UseCaseChange[]
    observedSessionCount: number
    highConfidenceShare: number
    comparisonWeeks: number
    onOpenRecording: (recordingId: string, timestampMs: number) => void
    onPromoteUseCase: (useCaseKey: string) => void
}

const CHART_CONFIG: TimeSeriesBarChartConfig = {
    barLayout: 'percent',
    bandPadding: 0.24,
    xAxis: { timezone: 'UTC', interval: 'week' },
    yAxis: { format: 'percentage_scaled', showGrid: true },
    legend: { show: true, position: 'bottom' },
    tooltip: { showTotal: true, totalLabel: 'Observed sessions' },
}

// Changing these data-attr values breaks autocapture dashboards and visual tests.
const REVIEW_CHANGE_DATA_ATTR = 'replay-vision-use-case-review-change'
const PROMOTE_USE_CASE_DATA_ATTR = 'replay-vision-use-case-promote'
const OPEN_RECORDING_DATA_ATTR = 'replay-vision-use-case-open-recording'
const USE_CASE_CHART_DATA_ATTR = 'replay-vision-use-case-mix-chart'

function changeTag(change: UseCaseChange): JSX.Element {
    if (change.direction === 'new') {
        return (
            <LemonTag type="highlight" icon={<IconSparkles />}>
                New
            </LemonTag>
        )
    }
    if (change.direction === 'growing') {
        return (
            <LemonTag type="success" icon={<IconTrending />}>
                +{change.percentagePointChange} points
            </LemonTag>
        )
    }
    return (
        <LemonTag type="muted" icon={<IconTrendingDown />}>
            {change.percentagePointChange} points
        </LemonTag>
    )
}

export function ReplayVisionUseCaseMapPrototype({
    productName,
    dateLabels,
    series,
    changes,
    observedSessionCount,
    highConfidenceShare,
    comparisonWeeks,
    onOpenRecording,
    onPromoteUseCase,
}: ReplayVisionUseCaseMapPrototypeProps): JSX.Element {
    const theme = useChartTheme()
    const [selectedUseCaseKey, setSelectedUseCaseKey] = useState(changes[0]?.key ?? '')
    const selectedChange = changes.find((change) => change.key === selectedUseCaseKey) ?? changes[0]

    return (
        <LemonCard hoverEffect={false} className="@container/use-case-map p-0 overflow-hidden">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4">
                <div className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <h2 className="m-0 text-base font-semibold">What people use {productName} for</h2>
                        <LemonTag type="muted">Dummy data</LemonTag>
                    </div>
                    <p className="m-0 max-w-3xl text-sm text-muted">
                        Replay Vision assigns each recording one primary use case from visible behavior. The chart shows
                        each use case&apos;s share of observed sessions, so scan volume does not change the mix.
                    </p>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted tabular-nums">
                    <span>{observedSessionCount.toLocaleString()} recordings observed</span>
                    <span>{highConfidenceShare}% high-confidence observations</span>
                </div>
            </div>

            <div className="grid grid-cols-1 @min-[48rem]/use-case-map:grid-cols-3">
                <section className="min-w-0 space-y-3 border-b p-4 @min-[48rem]/use-case-map:col-span-2 @min-[48rem]/use-case-map:border-b-0 @min-[48rem]/use-case-map:border-r">
                    <div>
                        <h3 className="m-0 text-sm font-semibold">Use case mix</h3>
                        <p className="m-0 text-xs text-muted">Weekly share of observed sessions</p>
                    </div>
                    <div className="h-80 flex flex-col">
                        <TimeSeriesBarChart
                            dataAttr={USE_CASE_CHART_DATA_ATTR}
                            labels={dateLabels}
                            series={series}
                            theme={theme}
                            config={CHART_CONFIG}
                        >
                            {selectedChange?.firstObservedAt ? (
                                <ReferenceLine
                                    value={selectedChange.firstObservedAt}
                                    orientation="vertical"
                                    variant="marker"
                                    label="First observed"
                                />
                            ) : null}
                        </TimeSeriesBarChart>
                    </div>
                </section>

                <aside className="space-y-3 p-4">
                    <div>
                        <h3 className="m-0 text-sm font-semibold">Changes worth reviewing</h3>
                        <p className="m-0 text-xs text-muted">Compared with the previous {comparisonWeeks} weeks</p>
                    </div>
                    {changes.length === 0 ? (
                        <p className="m-0 text-sm text-muted">No meaningful changes in this period.</p>
                    ) : (
                        <div className="space-y-2">
                            {changes.map((change) => {
                                const selected = change.key === selectedChange?.key
                                return (
                                    <LemonCard
                                        key={change.key}
                                        hoverEffect={false}
                                        focused={selected}
                                        className="space-y-2 p-3"
                                    >
                                        <div className="flex flex-wrap items-start justify-between gap-2">
                                            <div className="min-w-0">
                                                <div className="truncate text-sm font-medium" title={change.label}>
                                                    {change.label}
                                                </div>
                                                <div className="text-xs text-muted tabular-nums">
                                                    {change.currentShare}% now · {change.currentSessionCount} sessions
                                                </div>
                                            </div>
                                            {changeTag(change)}
                                        </div>
                                        <LemonButton
                                            type={selected ? 'primary' : 'secondary'}
                                            size="xsmall"
                                            onClick={() => setSelectedUseCaseKey(change.key)}
                                            data-attr={REVIEW_CHANGE_DATA_ATTR}
                                        >
                                            {selected ? 'Evidence selected' : 'Review evidence'}
                                        </LemonButton>
                                    </LemonCard>
                                )
                            })}
                        </div>
                    )}
                </aside>
            </div>

            {selectedChange ? (
                <section className="grid grid-cols-1 gap-4 border-t p-4 @min-[48rem]/use-case-map:grid-cols-3">
                    <div className="space-y-3">
                        <div className="space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                                <h3 className="m-0 text-sm font-semibold">{selectedChange.label}</h3>
                                <LemonTag
                                    type={selectedChange.source === 'freeform' ? 'highlight' : 'option'}
                                    icon={selectedChange.source === 'freeform' ? <IconSparkles /> : undefined}
                                >
                                    {selectedChange.source === 'freeform' ? 'Freeform tag' : 'Configured category'}
                                </LemonTag>
                            </div>
                            <p className="m-0 text-xs text-muted">
                                {selectedChange.firstObservedLabel
                                    ? `First observed ${selectedChange.firstObservedLabel}. `
                                    : ''}
                                Based on {selectedChange.currentSessionCount} recordings in the current period.
                            </p>
                        </div>
                        {selectedChange.source === 'freeform' ? (
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={() => onPromoteUseCase(selectedChange.key)}
                                data-attr={PROMOTE_USE_CASE_DATA_ATTR}
                            >
                                Add to scanner categories
                            </LemonButton>
                        ) : null}
                        <p className="m-0 text-xs text-muted">
                            Scanner judgments can be wrong. Review the cited moments before changing categories or
                            acting on a trend.
                        </p>
                    </div>

                    <div className="space-y-2 @min-[48rem]/use-case-map:col-span-2">
                        <h3 className="m-0 text-sm font-semibold">Why Replay Vision assigned this use case</h3>
                        <div className="grid grid-cols-1 gap-2 @min-[64rem]/use-case-map:grid-cols-2">
                            {selectedChange.evidence.map((evidence) => (
                                <LemonCard key={evidence.recordingId} hoverEffect={false} className="space-y-3 p-3">
                                    <p className="m-0 text-sm">{evidence.summary}</p>
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                        <LemonTag type="muted">
                                            {Math.round(evidence.confidence * 100)}% confidence
                                        </LemonTag>
                                        <LemonButton
                                            type="secondary"
                                            size="xsmall"
                                            icon={<IconPlay />}
                                            onClick={() => onOpenRecording(evidence.recordingId, evidence.timestampMs)}
                                            data-attr={OPEN_RECORDING_DATA_ATTR}
                                        >
                                            Watch {evidence.timestampLabel}
                                        </LemonButton>
                                    </div>
                                </LemonCard>
                            ))}
                        </div>
                    </div>
                </section>
            ) : null}
        </LemonCard>
    )
}
