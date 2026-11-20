import { type ReactNode, useMemo, useState } from 'react'

import { type ChartTheme, type TimeInterval, type TooltipContext } from '@posthog/quill-charts'
import { Button, ToggleGroup, ToggleGroupItem } from '@posthog/quill-primitives'

import { formatPercentage, sum } from 'lib/utils/numbers'

import { shadeColor } from '../colors'
import { Card, CardState } from '../dashboard/Card'
import { ChartSkeleton } from '../dashboard/ChartSkeleton'
import { ChartTooltip } from '../dashboard/ChartTooltip'
import { formatNumber } from '../dashboard/formatters'
import { ShareBarChart, type ShareBarRow } from '../dashboard/ShareBarChart'
import { type BucketedFacetRow, buildShareSeries, type ShareSeries } from './leaderboardShares'
import { LoadErrorMessage } from './LoadErrorMessage'
import { NoDataMessage } from './NoDataMessage'
import { ShareOverTimeChart, type ShareOverTimeSeries } from './ShareOverTimeChart'

// The rest fold into "Other" until someone expands the list. The over-time view always folds.
const TOP_ROWS = 6
// An expanded list scrolls past this many rows, so a long tail cannot stretch the card.
const EXPANDED_VISIBLE_ROWS = 10
const OTHER = 'Other'
const UNKNOWN = 'Unknown'

type ShareView = 'bars' | 'over-time'

interface BarMeta {
    calls: number
}

function renderTooltip(ctx: TooltipContext<BarMeta & { share: number }>): JSX.Element | null {
    const entry = ctx.seriesData[0]
    const meta = entry?.series.meta
    if (!entry || !meta) {
        return null
    }
    return (
        <ChartTooltip
            title={entry.series.label}
            rows={[
                ['Calls', formatNumber(meta.calls)],
                ['Share', formatPercentage(meta.share, { compact: true })],
            ]}
        />
    )
}

export function ShareWidget({
    title,
    description,
    rows,
    bucketKeys,
    loading,
    failed,
    theme,
    timezone,
    interval,
    dataAttr,
    labelOf = (label) => label,
    iconOf,
    onSelect,
    unknownLabel = UNKNOWN,
    setupEmptyState,
}: {
    title: string
    description?: ReactNode
    rows: BucketedFacetRow[]
    bucketKeys: string[]
    loading: boolean
    failed: boolean
    theme: ChartTheme
    timezone: string
    interval: TimeInterval
    dataAttr: string
    labelOf?: (label: string) => string
    iconOf?: (label: string) => ReactNode
    /** Makes each named row clickable. Receives the clicked label and every named label, in order. */
    onSelect?: (label: string, labels: string[]) => void
    unknownLabel?: string
    setupEmptyState?: ReactNode
}): JSX.Element {
    const [view, setView] = useState<ShareView>('bars')
    const [expanded, setExpanded] = useState(false)

    const { named, other, unknown } = useMemo(() => {
        const ranked = buildShareSeries(rows, bucketKeys, (label) => label, Infinity)
        return {
            named: ranked.filter((s) => s.label !== OTHER && s.label !== UNKNOWN),
            other: ranked.find((s) => s.label === OTHER),
            unknown: ranked.find((s) => s.label === UNKNOWN),
        }
    }, [rows, bucketKeys])

    // Palette by rank; Unknown a lighter gray than Other so they differ when stacked.
    const colorOf = useMemo(() => {
        const byLabel = new Map(named.map((s, index) => [s.label, theme.colors[index % theme.colors.length]]))
        const unknownColor = shadeColor(theme.axisColor, 40)
        return (label: string): string | undefined =>
            byLabel.get(label) ?? (label === UNKNOWN ? unknownColor : theme.axisColor)
    }, [named, theme])

    // Folding a single value into "Other" would only hide its name, so a list one past the cut shows whole.
    const topRows = named.length === TOP_ROWS + 1 ? named.length : TOP_ROWS
    const folded = useMemo<ShareSeries[]>(
        () => [
            ...buildShareSeries(rows, bucketKeys, (label) => (label === UNKNOWN ? null : label), topRows),
            ...(unknown ? [unknown] : []),
        ],
        [rows, bucketKeys, topRows, unknown]
    )

    const barSeries = expanded ? [...named, ...(other ? [other] : []), ...(unknown ? [unknown] : [])] : folded
    const totalCalls = useMemo(() => sum(folded.map((s) => sum(s.data))), [folded])
    const barRows = useMemo<ShareBarRow<BarMeta>[]>(
        () =>
            barSeries.map((s) => {
                const isCatchAll = s.label === OTHER || s.label === UNKNOWN
                const calls = sum(s.data)
                return {
                    key: s.label,
                    label: s.label === UNKNOWN ? unknownLabel : isCatchAll ? s.label : labelOf(s.label),
                    value: calls,
                    color: colorOf(s.label),
                    icon: isCatchAll ? undefined : iconOf?.(s.label),
                    onClick:
                        isCatchAll || !onSelect
                            ? undefined
                            : () =>
                                  onSelect(
                                      s.label,
                                      named.map((series) => series.label)
                                  ),
                    meta: { calls },
                }
            }),
        [barSeries, colorOf, labelOf, iconOf, onSelect, named, unknownLabel]
    )
    const overTimeSeries = useMemo<ShareOverTimeSeries[]>(
        () =>
            folded.map((s) => ({
                key: s.label,
                label: s.label === UNKNOWN ? unknownLabel : s.label === OTHER ? s.label : labelOf(s.label),
                color: colorOf(s.label),
                data: s.data,
            })),
        [folded, colorOf, labelOf, unknownLabel]
    )

    return (
        <Card
            title={title}
            description={description}
            className="min-w-0"
            action={
                setupEmptyState ? undefined : (
                    <ToggleGroup
                        className="-my-1"
                        value={[view]}
                        onValueChange={(next) => next[0] && setView(next[0] as ShareView)}
                        aria-label={`${title} view`}
                    >
                        <ToggleGroupItem value="bars" size="sm" data-attr={`${dataAttr}-view-bars`}>
                            Bars
                        </ToggleGroupItem>
                        <ToggleGroupItem value="over-time" size="sm" data-attr={`${dataAttr}-view-over-time`}>
                            Over time
                        </ToggleGroupItem>
                    </ToggleGroup>
                )
            }
        >
            <CardState
                loading={loading}
                isEmpty={totalCalls === 0 || !!setupEmptyState}
                className="min-h-48"
                skeleton={<ChartSkeleton kind={view === 'bars' ? 'shares' : 'line'} />}
                empty={failed ? <LoadErrorMessage /> : (setupEmptyState ?? <NoDataMessage />)}
            >
                {view === 'bars' ? (
                    <>
                        <ShareBarChart
                            rows={barRows}
                            totalCalls={totalCalls}
                            theme={theme}
                            tooltip={renderTooltip}
                            maxVisibleRows={expanded ? EXPANDED_VISIBLE_ROWS : undefined}
                            label={title}
                        />
                        {named.length > topRows ? (
                            <div>
                                <Button
                                    variant="link-muted"
                                    size="sm"
                                    className="px-0"
                                    onClick={() => setExpanded(!expanded)}
                                    data-attr={`${dataAttr}-${expanded ? 'show-top' : 'show-all'}`}
                                >
                                    {expanded ? `Show top ${TOP_ROWS}` : `Show all ${named.length}`}
                                </Button>
                            </div>
                        ) : null}
                    </>
                ) : (
                    <ShareOverTimeChart
                        labels={bucketKeys}
                        series={overTimeSeries}
                        theme={theme}
                        timezone={timezone}
                        interval={interval}
                    />
                )}
            </CardState>
        </Card>
    )
}
