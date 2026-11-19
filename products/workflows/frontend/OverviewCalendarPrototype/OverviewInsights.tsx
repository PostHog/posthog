// PROTOTYPE (throwaway): overview B2, round 2. Performance first with insights: a headline, the numbers, how
// messages turn into conversions, what people do after a click, replay vision, the best time to send and send
// health. A side rail keeps the small parts of A: what needs attention, the next 7 days and drafts.
import { useMemo, useState } from 'react'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'
import { BarList, FunnelChart, Heatmap, TimeSeriesBarChart, funnelFromCounts } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'

import { AfterClickCard } from './AfterClickCard'
import { AttentionCompact } from './AttentionCompact'
import { ChartCard } from './ChartCard'
import { DeliverabilityCard } from './DeliverabilityCard'
import { DraftsList } from './DraftsList'
import {
    CONVERSIONS_SERIES,
    CONVERSION_RATE,
    ChannelFilter,
    SEND_TIME_DAYS,
    SEND_TIME_HOURS,
    SEND_TIME_OPENS,
    TOP_MESSAGES,
    dailyTotals,
    seriesFor,
    weightedRate,
} from './insightsData'
import { OverviewMetric } from './OverviewMetric'
import { EntryKind, SERIES_LABELS, formatCount, sum } from './prototypeData'
import { ReplayScannerCard } from './ReplayScannerCard'
import { WeekAhead } from './WeekAhead'

const CHANNELS: { value: ChannelFilter; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'email', label: 'Email' },
    { value: 'sms', label: 'SMS' },
    { value: 'push', label: 'Push' },
]

const KINDS: { kind: EntryKind; label: string; dot: string }[] = [
    { kind: 'broadcast', label: 'Broadcasts', dot: 'bg-[var(--data-color-1)]' },
    { kind: 'workflow', label: 'Workflows', dot: 'bg-[var(--data-color-2)]' },
    { kind: 'transactional', label: 'Transactional', dot: 'bg-[var(--data-color-3)]' },
]

const VOLUME_CONFIG = { xAxis: { timezone: 'UTC', interval: 'day' as const }, yAxis: { showGrid: true } }
const HEATMAP_CONFIG = { xTickFormatter: (label: string, i: number) => (i % 3 === 0 ? label : null) }
const TOP_CONFIG = { valueDisplay: 'value' as const }

export function OverviewInsights(): JSX.Element {
    const theme = useChartTheme()
    const [channel, setChannel] = useState<ChannelFilter>('all')

    const rows = useMemo(() => seriesFor(channel), [channel])
    const daily = useMemo(() => dailyTotals(rows), [rows])
    const sent = sum(daily)
    const deliveredRate = weightedRate(rows, (r) => r.deliveredRate)
    const opensApply = channel !== 'sms'
    const openRate = weightedRate(
        rows.filter((r) => r.channel !== 'sms'),
        (r) => r.openRate
    )
    const clickRate = weightedRate(rows, (r) => r.clickRate)
    const delivered = Math.round(sent * deliveredRate)
    const opened = Math.round(delivered * openRate)
    const clicked = Math.round(delivered * clickRate)
    const converted = Math.round(clicked * CONVERSION_RATE[channel])

    const volume = useMemo(
        () =>
            KINDS.map(({ kind, label }) => ({
                key: kind,
                label,
                data: dailyTotals(rows.filter((r) => r.kind === kind)),
            })),
        [rows]
    )
    const funnel = useMemo(
        () =>
            funnelFromCounts(
                [
                    { label: 'Sent', count: sent },
                    { label: 'Delivered', count: delivered },
                    ...(opensApply ? [{ label: 'Opened', count: opened }] : []),
                    { label: 'Clicked', count: clicked },
                    { label: 'Converted', count: converted },
                ],
                { label: 'Messages' }
            ),
        [sent, delivered, opened, clicked, converted, opensApply]
    )
    const funnelCounts = [sent, delivered, ...(opensApply ? [opened] : []), clicked, converted]
    const top = useMemo(
        () => TOP_MESSAGES.map((m) => ({ key: m.key, label: m.label, data: [Math.round(m.clickRate * 1000) / 10] })),
        []
    )

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-end justify-between gap-4">
                <div className="flex max-w-3xl flex-col gap-1">
                    <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Last 30 days
                    </span>
                    <p className="mb-0 text-2xl font-semibold leading-snug">
                        {formatCount(delivered)} messages reached people, and{' '}
                        <span className="text-success-foreground">{formatCount(converted)} converted</span> after one,
                        18% more than the 30 days before.
                    </p>
                </div>
                <ToggleGroup
                    variant="outline"
                    aria-label="Channel"
                    value={[channel]}
                    onValueChange={(next: string[]) => next[0] && setChannel(next[0] as ChannelFilter)}
                >
                    {CHANNELS.map((c) => (
                        <ToggleGroupItem key={c.value} value={c.value}>
                            {c.label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>

            <div className="grid grid-cols-2 gap-3 @min-[48rem]:grid-cols-3 @min-[72rem]:grid-cols-5">
                <OverviewMetric title="Messages sent" value={sent} data={daily} change={12} format={formatCount} />
                <OverviewMetric
                    title="Delivered"
                    value={deliveredRate * 100}
                    change={-0.4}
                    format={(v) => `${v.toFixed(1)}%`}
                    subtitle={`${formatCount(delivered)} messages`}
                />
                {opensApply ? (
                    <OverviewMetric
                        title="Opened"
                        value={openRate * 100}
                        change={3}
                        format={(v) => `${v.toFixed(0)}%`}
                        subtitle={`${formatCount(opened)} of messages delivered`}
                    />
                ) : (
                    <OverviewMetric title="Replies" value={42} change={8} subtitle="6 were STOP" />
                )}
                <OverviewMetric
                    title="Clicked"
                    value={clickRate * 100}
                    change={1}
                    format={(v) => `${v.toFixed(1)}%`}
                    subtitle={`${formatCount(clicked)} people`}
                />
                <OverviewMetric
                    title="Converted"
                    value={converted}
                    data={CONVERSIONS_SERIES}
                    change={18}
                    format={formatCount}
                />
            </div>

            <div className="grid gap-6 @min-[72rem]:grid-cols-[minmax(0,1fr)_20rem]">
                <div className="flex min-w-0 flex-col gap-6">
                    <ChartCard
                        title="Messages sent per day"
                        description="By messaging type"
                        action={
                            <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
                                {KINDS.map((k) => (
                                    <span key={k.kind} className="inline-flex items-center gap-1">
                                        <span aria-hidden className={`size-2 rounded-xs ${k.dot}`} />
                                        {k.label}
                                    </span>
                                ))}
                            </div>
                        }
                    >
                        <div className="flex h-56 flex-col">
                            <TimeSeriesBarChart
                                series={volume}
                                labels={SERIES_LABELS}
                                theme={theme}
                                config={VOLUME_CONFIG}
                            />
                        </div>
                    </ChartCard>

                    <div className="grid gap-6 @min-[56rem]:grid-cols-2">
                        <ChartCard
                            title="From message to conversion"
                            description="Converted: did the goal event within 7 days of a click"
                        >
                            <div className="flex h-64 flex-col">
                                <FunnelChart
                                    steps={funnel.steps}
                                    series={funnel.series}
                                    theme={theme}
                                    stepFooter={(i) => (
                                        <div className="text-xs leading-tight">
                                            <div className="truncate font-semibold">{funnel.steps[i]}</div>
                                            <div className="text-muted-foreground">
                                                {formatCount(funnelCounts[i] ?? 0)}
                                            </div>
                                        </div>
                                    )}
                                />
                            </div>
                        </ChartCard>
                        <ChartCard
                            title="Best time to send"
                            description="Email opens by weekday and hour. Tuesday at 9:00 gets the most."
                        >
                            <div className="flex h-64 flex-col">
                                <Heatmap
                                    xLabels={SEND_TIME_HOURS}
                                    yLabels={SEND_TIME_DAYS}
                                    cells={SEND_TIME_OPENS}
                                    theme={theme}
                                    config={HEATMAP_CONFIG}
                                />
                            </div>
                        </ChartCard>
                    </div>

                    <div className="grid gap-6 @min-[56rem]:grid-cols-[3fr_2fr]">
                        <AfterClickCard />
                        <ReplayScannerCard />
                    </div>

                    <div className="grid gap-6 @min-[56rem]:grid-cols-2">
                        <ChartCard title="Top messages by click rate" description="Last 30 days, at least 500 sent">
                            <div className="flex h-48 flex-col">
                                <BarList
                                    series={top}
                                    theme={theme}
                                    config={TOP_CONFIG}
                                    valueFormatter={(v) => `${v.toFixed(1)}%`}
                                />
                            </div>
                        </ChartCard>
                        <DeliverabilityCard />
                    </div>
                </div>

                <aside className="flex min-w-0 flex-col gap-4">
                    <AttentionCompact />
                    <WeekAhead />
                    <DraftsList />
                </aside>
            </div>
        </div>
    )
}
