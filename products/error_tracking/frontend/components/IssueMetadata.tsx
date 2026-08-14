import { useActions, useValues } from 'kea'
import { PropsWithChildren, UIEvent, useCallback, useMemo, useRef } from 'react'
import { match } from 'ts-pattern'

import { IconArrowLeft, IconClock, IconListTree, IconTrending } from '@posthog/icons'
import { Tooltip as LemonTooltip } from '@posthog/lemon-ui'

import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import {
    Button,
    Heading,
    Skeleton,
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
            <div
                className="flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-y-none [scrollbar-gutter:stable]"
                onScroll={handleScroll}
            >
                <div className="max-h-1/2 shrink-0 overflow-y-auto overscroll-y-none">
                    <Tabs
                        orientation="vertical"
                        value={activePreview}
                        onValueChange={(preview) => {
                            if (preview === 'time' || preview === 'properties') {
                                setActivePreview(preview)
                            }
                        }}
                        data-quill
                        className="relative items-stretch gap-0 border-b border-primary bg-[var(--background)] after:pointer-events-none after:absolute after:inset-y-0 after:left-10 after:z-10 after:border-l after:border-primary after:content-['']"
                    >
                        <TabsList
                            variant="line"
                            aria-label="Issue filter previews"
                            className="sticky top-0 z-20 !h-auto w-10 shrink-0 justify-start self-start rounded-none bg-[var(--background)] p-1"
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
                        <TabsContent value="time" className="min-w-0 !flex-none flex-1">
                            <TimeFilterPreview />
                        </TabsContent>
                        <TabsContent value="properties" className="min-w-0 !flex-none flex-1">
                            <MiniBreakdowns />
                        </TabsContent>
                    </Tabs>
                </div>
                {children}
            </div>
        </div>
    )
}

function TimeFilterPreview(): JSX.Element {
    const { issueId, spikeEvents } = useValues(errorTrackingIssueSceneLogic)
    const sparklineKey = issueId || 'issue-unknown'
    const { clickedSpike } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { setClickedSpike } = useActions(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { applyDateRangeFilter } = useActions(issueFilterPreviewLogic)
    const sparklineData = useSparklineDataIssueScene()
    const sparklineEvents = useSparklineEvents()
    const sparklineContainerRef = useRef<HTMLDivElement | null>(null)

    const handleRangeSelect = useCallback(
        (startDate: Date, endDate: Date) => {
            setClickedSpike(null)
            applyDateRangeFilter({
                date_from: startDate.toISOString(),
                date_to: endDate.toISOString(),
            })
        },
        [applyDateRangeFilter, setClickedSpike]
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
            (spikeEvents as ErrorTrackingSpikeEvent[]).find((spikeEvent) => {
                const detectedAt = new Date(spikeEvent.detected_at).getTime()
                return detectedAt >= binStart && detectedAt < binStart + binSizeMs
            }) ?? null
        )
    }, [clickedSpike, spikeEvents, sparklineData])

    return (
        <div className="relative flex flex-col">
            <MetadataHeader sparklineKey={sparklineKey} />
            <LemonTooltip title="Click a bar or drag to select a date range">
                <div
                    onClick={cancelEvent}
                    ref={sparklineContainerRef}
                    className="relative flex h-56 w-full flex-col px-4 py-3"
                >
                    <VolumeSparkline
                        data={sparklineData}
                        layout="detailed"
                        xAxis="full"
                        events={sparklineEvents}
                        sparklineKey={sparklineKey}
                        className="h-full"
                        onRangeSelect={handleRangeSelect}
                        onBucketClick={handleRangeSelect}
                        onSpikeClick={handleSpikeClick}
                    />
                </div>
            </LemonTooltip>
            {clickedSpike && (
                <SpikeDetailsPopover
                    datum={clickedSpike.datum}
                    clientX={clickedSpike.clientX}
                    clientY={clickedSpike.clientY}
                    spikeEvent={matchedSpikeEvent}
                    onClose={() => setClickedSpike(null)}
                    sparklineContainerRef={sparklineContainerRef}
                />
            )}
        </div>
    )
}

/** Owns the `hoverSelection` read because reading it above would re-render the chart subtree on every mouse move. */
function MetadataHeader({ sparklineKey }: { sparklineKey: string }): JSX.Element {
    const { aggregations, summaryLoading } = useValues(errorTrackingIssueSceneLogic)
    const { hoverSelection } = useValues(errorTrackingVolumeSparklineLogic({ sparklineKey }))
    const { activePreview, canUndoActivePreview } = useValues(issueFilterPreviewLogic)
    const { resetAllFilters, undoActivePreview } = useActions(issueFilterPreviewLogic)
    const canUndo = activePreview === 'time' && canUndoActivePreview

    return (
        <div className="sticky top-0 z-10 flex h-10 shrink-0 items-center justify-between border-b border-primary bg-[var(--background)] px-4">
            <div className="flex items-center gap-2">
                <div className="flex size-6 shrink-0 items-center justify-center">
                    {canUndo ? (
                        <LemonTooltip title="Undo filter">
                            <Button
                                variant="default"
                                size="icon-sm"
                                aria-label="Undo filter"
                                data-attr="error-tracking-undo-preview-filter"
                                onClick={undoActivePreview}
                            >
                                <IconArrowLeft />
                            </Button>
                        </LemonTooltip>
                    ) : (
                        <LemonTooltip title="Reset all filters">
                            <Button
                                variant="default"
                                size="icon-sm"
                                aria-label="Reset all filters"
                                data-attr="error-tracking-reset-all-filters"
                                onClick={resetAllFilters}
                            >
                                <IconClock />
                            </Button>
                        </LemonTooltip>
                    )}
                </div>
                <Heading size="sm">Volume</Heading>
            </div>
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
                .with([true], () => (
                    <Skeleton className="h-2 w-[50px]">
                        <span>Loading…</span>
                    </Skeleton>
                ))
                .with([false], () => (
                    <LemonTooltip title={tooltip} delayMs={0} placement="right">
                        <div className="flex items-center gap-1">
                            <div className="text-lg font-bold inline-block">
                                {value == null ? '0' : humanFriendlyLargeNumber(value)}
                            </div>
                            <div className="inline-block text-xs text-muted-foreground">{name}</div>
                        </div>
                    </LemonTooltip>
                ))
                .exhaustive()}
        </span>
    )
}

function renderDataPoint(datum: SparklineDatum): JSX.Element {
    return (
        <div className="flex items-center h-full gap-3">
            {renderMetric('Occurrences', datum.value, false)}
            {datum.isSpike && (
                <div className="flex items-center gap-1.5 text-warning-foreground">
                    <IconTrending className="text-base" />
                    <span className="text-xs font-semibold">Spike</span>
                    <span className="text-xs text-muted-foreground">Click to filter</span>
                </div>
            )}
        </div>
    )
}

function renderEventPoint(event: SparklineEvent<string>): JSX.Element {
    return (
        <div className="flex h-full items-center justify-start">
            <div className="text-sm font-semibold">{dayjs(event.date).utc().format('D MMM YYYY HH:mm [UTC]')}</div>
        </div>
    )
}
