import { useActions, useValues } from 'kea'
import { PropsWithChildren, UIEvent, useCallback, useMemo, useRef } from 'react'
import { match } from 'ts-pattern'

import { IconChevronRight, IconClock, IconListTree, IconTrending } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip as QuillTooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'

import { ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { useSparklineDataIssueScene } from '../hooks/use-sparkline-data'
import { useSparklineEvents } from '../hooks/use-sparkline-events'
import { errorTrackingIssueSceneLogic } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { cancelEvent } from '../utils'
import { MiniBreakdowns } from './Breakdowns/MiniBreakdowns'
import { issueFilterPreviewLogic } from './IssueFilterPreview/issueFilterPreviewLogic'
import { SpikeDetailsPopover } from './SpikeDetailsPopover'
import { TimeBoundary } from './TimeBoundary'
import { errorTrackingVolumeSparklineLogic } from './VolumeSparkline/errorTrackingVolumeSparklineLogic'
import type { SparklineDatum, SparklineEvent, VolumeSparklineHoverSelection } from './VolumeSparkline/types'
import { VolumeSparkline } from './VolumeSparkline/VolumeSparkline'

export const Metadata = ({
    children,
    className,
    onScrollNearEnd,
}: PropsWithChildren<{ className?: string; onScrollNearEnd?: () => void }>): JSX.Element => {
    const { activePreview } = useValues(issueFilterPreviewLogic)
    const { setActivePreview } = useActions(issueFilterPreviewLogic)

    const handleScroll = (event: UIEvent<HTMLDivElement>): void => {
        const { clientHeight, scrollHeight, scrollTop } = event.currentTarget
        if (scrollHeight - scrollTop - clientHeight <= 400) {
            onScrollNearEnd?.()
        }
    }

    return (
        <div className={className}>
            <div className="flex-1 min-h-0 overflow-y-auto [scrollbar-gutter:stable]" onScroll={handleScroll}>
                <Tabs
                    orientation="vertical"
                    value={activePreview}
                    onValueChange={(preview) => {
                        if (preview === 'time' || preview === 'properties') {
                            setActivePreview(preview)
                        }
                    }}
                    data-quill
                    className="h-[216px] shrink-0 gap-0 border-b border-primary bg-[var(--background)]"
                >
                    <TabsList
                        variant="line"
                        aria-label="Issue filter previews"
                        className="!h-full w-10 shrink-0 justify-start rounded-none border-r border-primary p-1"
                    >
                        <QuillTooltip>
                            <TooltipTrigger
                                render={
                                    <TabsTrigger
                                        value="time"
                                        aria-label="Time"
                                        className="!size-8 !flex-none !justify-center !p-0"
                                    />
                                }
                            >
                                <IconClock />
                            </TooltipTrigger>
                            <TooltipContent side="right">Time</TooltipContent>
                        </QuillTooltip>
                        <QuillTooltip>
                            <TooltipTrigger
                                render={
                                    <TabsTrigger
                                        value="properties"
                                        aria-label="Properties"
                                        className="!size-8 !flex-none !justify-center !p-0"
                                    />
                                }
                            >
                                <IconListTree />
                            </TooltipTrigger>
                            <TooltipContent side="right">Properties</TooltipContent>
                        </QuillTooltip>
                    </TabsList>
                    <TabsContent value="time" className="min-w-0 flex-1">
                        <TimeFilterPreview />
                    </TabsContent>
                    <TabsContent value="properties" className="min-w-0 flex-1">
                        <MiniBreakdowns />
                    </TabsContent>
                </Tabs>
                {children}
            </div>
        </div>
    )
}

function TimeFilterPreview(): JSX.Element {
    const { aggregations, summaryLoading, issueLoading, firstSeen, lastSeen, issueId, spikeEvents } =
        useValues(errorTrackingIssueSceneLogic)
    const { setDateRange } = useActions(errorTrackingIssueSceneLogic)
    const sparklineKey = issueId || 'issue-unknown'
    const { hoverSelection, clickedSpike } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { setClickedSpike } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const sparklineData = useSparklineDataIssueScene()
    const sparklineEvents = useSparklineEvents()
    const sparklineContainerRef = useRef<HTMLDivElement | null>(null)

    const handleRangeSelect = useCallback(
        (startDate: Date, endDate: Date) => {
            setClickedSpike(null)
            setDateRange({
                date_from: startDate.toISOString(),
                date_to: endDate.toISOString(),
            })
        },
        [setDateRange, setClickedSpike]
    )

    const handleSpikeClick = useCallback(
        (datum: SparklineDatum, clientX: number, clientY: number) => {
            setClickedSpike({ datum, clientX, clientY })
        },
        [setClickedSpike]
    )

    const matchedSpikeEvent = useMemo<ErrorTrackingSpikeEvent | null>(() => {
        if (!clickedSpike || sparklineData.length < 2) {
            return null
        }
        const binSizeMs = sparklineData[1].date.getTime() - sparklineData[0].date.getTime()
        const binStart = clickedSpike.datum.date.getTime()
        return (
            (spikeEvents as ErrorTrackingSpikeEvent[]).find((s) => {
                const t = new Date(s.detected_at).getTime()
                return t >= binStart && t < binStart + binSizeMs
            }) ?? null
        )
    }, [clickedSpike, spikeEvents, sparklineData])

    return (
        <div className="relative h-full">
            <div className="flex h-10 items-center justify-between px-4">
                <div className="flex h-full items-center justify-end">
                    {match(hoverSelection)
                        .when(
                            (data) => shouldRenderIssueMetrics(data),
                            () => <IssueMetrics aggregations={aggregations} summaryLoading={summaryLoading} />
                        )
                        .with({ kind: 'bin' }, (data) => renderDataPoint(data.datum))
                        .with({ kind: 'event' }, (data) => renderEventPoint(data.event))
                        .otherwise(() => null)}
                </div>
                <div className="flex h-full items-center justify-end">
                    {match(hoverSelection)
                        .with({ kind: 'bin' }, (data) => renderDate(data.datum.date))
                        .with({ kind: 'event' }, (data) => renderDate(data.event.date))
                        .otherwise(() => (
                            <>
                                <TimeBoundary
                                    time={firstSeen}
                                    loading={issueLoading}
                                    label="First seen"
                                    updateDateRange={(dateRange) => {
                                        dateRange.date_from = firstSeen?.toISOString()
                                        return dateRange
                                    }}
                                />
                                <IconChevronRight />
                                <TimeBoundary
                                    time={lastSeen}
                                    loading={summaryLoading}
                                    label="Last seen"
                                    updateDateRange={(dateRange) => {
                                        dateRange.date_to = lastSeen?.endOf('minute').toISOString()
                                        return dateRange
                                    }}
                                />
                            </>
                        ))}
                </div>
            </div>
            <Tooltip title="Drag to select a date range">
                <div
                    onClick={cancelEvent}
                    ref={sparklineContainerRef}
                    className="relative flex h-44 w-full flex-col px-4"
                >
                    <VolumeSparkline
                        data={sparklineData}
                        layout="detailed"
                        xAxis="full"
                        events={sparklineEvents}
                        sparklineKey={sparklineKey}
                        className="h-full"
                        onRangeSelect={handleRangeSelect}
                        onSpikeClick={handleSpikeClick}
                    />
                </div>
            </Tooltip>
            {clickedSpike && (
                <div className="contents">
                    <SpikeDetailsPopover
                        datum={clickedSpike.datum}
                        clientX={clickedSpike.clientX}
                        clientY={clickedSpike.clientY}
                        spikeEvent={matchedSpikeEvent}
                        onClose={() => setClickedSpike(null)}
                        sparklineContainerRef={sparklineContainerRef}
                    />
                </div>
            )}
        </div>
    )
}

function shouldRenderIssueMetrics(data: VolumeSparklineHoverSelection | null): boolean {
    if (data == null) {
        return true
    }
    if (data.kind === 'bin' && data.datum.value == 0) {
        return true
    }
    return false
}

function IssueMetrics({
    aggregations,
    summaryLoading,
}: {
    aggregations: ErrorTrackingIssueAggregations | undefined
    summaryLoading: boolean
}): JSX.Element {
    const hasSessionCount = aggregations && aggregations.sessions !== 0
    return (
        <div className="flex items-center h-full gap-3">
            {renderMetric('Occurrences', aggregations?.occurrences, summaryLoading)}
            {renderMetric(
                'Sessions',
                aggregations?.sessions,
                summaryLoading,
                hasSessionCount ? undefined : 'No $session_id was set for any event in this issue'
            )}
            {renderMetric('Users', aggregations?.users, summaryLoading)}
        </div>
    )
}

function renderMetric(name: string, value: number | undefined, loading: boolean, tooltip?: string): JSX.Element {
    return (
        <span className="contents">
            {match([loading])
                .with([true], () => <LemonSkeleton className="w-[50px] h-2" />)
                .with([false], () => (
                    <Tooltip title={tooltip} delayMs={0} placement="right">
                        <div className="flex items-center gap-1">
                            <div className="text-lg font-bold inline-block">
                                {value == null ? '0' : humanFriendlyLargeNumber(value)}
                            </div>
                            <div className="inline-block text-xs text-muted-foreground">{name}</div>
                        </div>
                    </Tooltip>
                ))
                .exhaustive()}
        </span>
    )
}

function renderDate(date: Date): JSX.Element {
    return (
        <div className="whitespace-nowrap text-xs text-muted-foreground">
            {dayjs(date).utc().format('D MMM YYYY HH:mm (UTC)')}
        </div>
    )
}

function renderDataPoint(d: SparklineDatum): JSX.Element {
    return (
        <div className="flex items-center h-full gap-3">
            {renderMetric('Occurrences', d.value, false)}
            {d.animated && (
                <div className="flex items-center gap-1.5 text-warning-foreground">
                    <IconTrending className="text-base" />
                    <span className="text-xs font-semibold">Spike</span>
                    <span className="text-xs text-muted-foreground">Click for details</span>
                </div>
            )}
        </div>
    )
}

function renderEventPoint(d: SparklineEvent<string>): JSX.Element {
    return (
        <div className="flex justify-start items-center h-full gap-1">
            <div className="text-lg font-bold">{d.payload}</div>
        </div>
    )
}
