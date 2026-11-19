// PROTOTYPE (throwaway): overview B3, round 3. Performance first: filters for period, topic and channel, five
// numbers, sends per day, message to conversion next to the top messages, what people do after a click next to
// replay vision, suggested improvements, and deliverability. A side rail keeps what needs attention, the next 7
// days and drafts. `newAccount` shows the empty states and the steps that fill them.
import { useMemo, useState } from 'react'

import { TimeSeriesBarChart } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { AfterClickCard } from './AfterClickCard'
import { AttentionCompact } from './AttentionCompact'
import { ChartCard } from './ChartCard'
import { ConversionCard } from './ConversionCard'
import { DeliverabilityCard } from './DeliverabilityCard'
import { DraftsList } from './DraftsList'
import { EmptyInsight } from './EmptyInsight'
import {
    CONVERSION_GOALS,
    CONVERSION_RATE,
    CONVERSIONS_SERIES,
    DEFAULT_OVERVIEW_FILTERS,
    OverviewFilterState,
    dailyTotals,
    filteredRows,
    forPeriod,
    periodLabels,
    topicFactor,
    weightedRate,
} from './insightsData'
import { OverviewFilterBar } from './OverviewFilterBar'
import { OverviewMetric } from './OverviewMetric'
import { EntryKind, formatCount, sum } from './prototypeData'
import { ReplayScannerCard } from './ReplayScannerCard'
import { SetupChecklist } from './SetupChecklist'
import { SuggestionsCard } from './SuggestionsCard'
import { TopMessagesCard } from './TopMessagesCard'
import { WeekAhead } from './WeekAhead'

const KINDS: { kind: EntryKind; label: string; dot: string }[] = [
    { kind: 'broadcast', label: 'Broadcasts', dot: 'bg-[var(--data-color-1)]' },
    { kind: 'workflow', label: 'Workflows', dot: 'bg-[var(--data-color-2)]' },
    { kind: 'transactional', label: 'Transactional', dot: 'bg-[var(--data-color-3)]' },
]

const VOLUME_CONFIG = { xAxis: { timezone: 'UTC', interval: 'day' as const }, yAxis: { showGrid: true } }

export function OverviewInsights({ newAccount = false }: { newAccount?: boolean }): JSX.Element {
    const theme = useChartTheme()
    const [filters, setFilters] = useState<OverviewFilterState>(DEFAULT_OVERVIEW_FILTERS)
    const [goal, setGoal] = useState<string | null>(newAccount ? null : 'upgraded')

    const factor = newAccount ? 0 : topicFactor(filters)
    const rows = useMemo(() => filteredRows(filters), [filters])
    const daily = useMemo(
        () => forPeriod(dailyTotals(rows), filters.period).map((v) => Math.round(v * factor)),
        [rows, filters.period, factor]
    )
    const sent = sum(daily)
    const deliveredRate = weightedRate(rows, (r) => r.deliveredRate)
    const opensApply = filters.channel !== 'sms'
    const openRate = weightedRate(
        rows.filter((r) => r.channel !== 'sms'),
        (r) => r.openRate
    )
    const clickRate = weightedRate(rows, (r) => r.clickRate)
    const delivered = Math.round(sent * deliveredRate)
    const opened = Math.round(delivered * openRate)
    const clicked = Math.round(delivered * clickRate)
    const goalFactor = CONVERSION_GOALS.find((g) => g.key === goal)?.factor ?? 0
    const converted = Math.round(clicked * CONVERSION_RATE[filters.channel] * goalFactor)
    const conversions = useMemo(
        () => forPeriod(CONVERSIONS_SERIES, filters.period).map((v) => Math.round(v * factor * goalFactor)),
        [filters.period, factor, goalFactor]
    )
    const labels = useMemo(() => periodLabels(filters.period), [filters.period])
    const volume = useMemo(
        () =>
            KINDS.map(({ kind, label }) => ({
                key: kind,
                label,
                data: forPeriod(dailyTotals(rows.filter((r) => r.kind === kind)), filters.period).map((v) =>
                    Math.round(v * factor)
                ),
            })),
        [rows, filters.period, factor]
    )
    const steps = useMemo(
        () => [
            { label: 'Sent', count: sent },
            { label: 'Delivered', count: delivered },
            ...(opensApply ? [{ label: 'Opened', count: opened }] : []),
            { label: 'Clicked', count: clicked },
            { label: 'Converted', count: converted },
        ],
        [sent, delivered, opened, clicked, converted, opensApply]
    )
    const noSends = newAccount
    const rate = (value: number): number => (noSends ? 0 : value * 100)

    return (
        <div className="flex flex-col gap-6">
            <OverviewFilterBar filters={filters} onChange={setFilters} />

            <div className="grid grid-cols-2 gap-3 @min-[48rem]:grid-cols-3 @min-[72rem]:grid-cols-5">
                <OverviewMetric
                    title="Messages sent"
                    value={sent}
                    data={noSends ? undefined : daily}
                    change={noSends ? undefined : 12}
                    format={formatCount}
                    subtitle={noSends ? 'None yet' : undefined}
                />
                <OverviewMetric
                    title="Delivered"
                    value={rate(deliveredRate)}
                    change={noSends ? undefined : -0.4}
                    format={(v) => (noSends ? '-' : `${v.toFixed(1)}%`)}
                    subtitle={noSends ? 'None yet' : `${formatCount(delivered)} messages`}
                />
                {opensApply ? (
                    <OverviewMetric
                        title="Opened"
                        value={rate(openRate)}
                        change={noSends ? undefined : 3}
                        format={(v) => (noSends ? '-' : `${v.toFixed(0)}%`)}
                        subtitle={noSends ? 'None yet' : `${formatCount(opened)} of messages delivered`}
                    />
                ) : (
                    <OverviewMetric title="Replies" value={noSends ? 0 : 42} change={8} subtitle="6 were STOP" />
                )}
                <OverviewMetric
                    title="Clicked"
                    value={rate(clickRate)}
                    change={noSends ? undefined : 1}
                    format={(v) => (noSends ? '-' : `${v.toFixed(1)}%`)}
                    subtitle={noSends ? 'None yet' : `${formatCount(clicked)} people`}
                />
                <OverviewMetric
                    title="Converted"
                    value={converted}
                    data={noSends || !goal ? undefined : conversions}
                    change={noSends || !goal ? undefined : 18}
                    format={(v) => (goal ? formatCount(v) : '-')}
                    subtitle={goal ? undefined : 'Pick a conversion goal'}
                />
            </div>

            <div className="grid gap-6 @min-[72rem]:grid-cols-[minmax(0,1fr)_20rem]">
                <div className="flex min-w-0 flex-col gap-6">
                    <ChartCard
                        title="Messages sent per day"
                        description="By messaging type"
                        action={
                            noSends ? null : (
                                <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                                    {KINDS.map((k) => (
                                        <span key={k.kind} className="inline-flex items-center gap-1">
                                            <span aria-hidden className={`size-2 rounded-xs ${k.dot}`} />
                                            {k.label}
                                        </span>
                                    ))}
                                </div>
                            )
                        }
                    >
                        {noSends ? (
                            <EmptyInsight
                                title="No messages sent yet"
                                detail="Broadcasts, workflows and transactional emails show here by day once they go out."
                            />
                        ) : (
                            <div className="flex h-56 flex-col">
                                <TimeSeriesBarChart
                                    series={volume}
                                    labels={labels}
                                    theme={theme}
                                    config={VOLUME_CONFIG}
                                />
                            </div>
                        )}
                    </ChartCard>

                    <div className="grid gap-6 @min-[56rem]:grid-cols-2">
                        <ConversionCard steps={steps} goal={goal} onGoal={setGoal} noSends={noSends} />
                        <TopMessagesCard noSends={noSends} />
                    </div>

                    <div className="grid gap-6 @min-[56rem]:grid-cols-[3fr_2fr]">
                        <AfterClickCard noSends={noSends} />
                        <ReplayScannerCard noScanner={newAccount} />
                    </div>

                    <SuggestionsCard noSends={noSends} />

                    <DeliverabilityCard noDomain={newAccount} />
                </div>

                <aside className="flex min-w-0 flex-col gap-4">
                    {newAccount ? <SetupChecklist /> : <AttentionCompact />}
                    <WeekAhead noSends={noSends} />
                    {newAccount ? null : <DraftsList />}
                </aside>
            </div>
        </div>
    )
}
