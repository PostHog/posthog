import { Fragment } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Button, Spinner, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import type { RecordingTimeline as RecordingTimelineData, TimelineRow } from '../utils/recordingTimeline'
import { MIN_INACTIVE_ROW_MS, currentRowIndex, rowStartMs, timelineGapPx } from '../utils/recordingTimeline'
import { QuillObservationThumbnail } from './QuillObservationThumbnail'
import { QuillTimelineRail } from './QuillTimelineRail'

export interface QuillRecordingTimelineProps {
    timeline: RecordingTimelineData
    rows: TimelineRow[]
    currentTimeMs: number
    onSeek: (timestampMs: number) => void
    onSummarize: () => void
    summarizing: boolean
    summarizeDisabledReason?: string | null
}

const ROW_GRID = 'grid grid-cols-[2.5rem_1rem_minmax(0,1fr)] gap-x-1.5 px-2'
const ROW_GRID_HOURS = 'grid grid-cols-[4rem_1rem_minmax(0,1fr)] gap-x-1.5 px-2'
const HOUR_MS = 3_600_000

const formatSpan = (ms: number): string => humanFriendlyDuration(ms / 1000, { maxUnits: 1 })

export function QuillSummaryNotice({
    timeline,
    onSummarize,
    summarizing,
    summarizeDisabledReason,
}: QuillRecordingTimelineProps): JSX.Element | null {
    if (timeline.summaryState === 'ready') {
        return null
    }
    if (timeline.summaryState === 'pending') {
        return (
            <div
                className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground"
                data-attr="vision-timeline-pending"
            >
                <Spinner /> Building the timeline of this recording…
            </div>
        )
    }
    const outdated = timeline.summaryState === 'outdated'
    return (
        <div className="flex flex-col items-start gap-2 px-3 py-3" data-attr="vision-timeline-cta">
            <span className="text-xs text-muted-foreground">
                {outdated
                    ? 'This recording was summarized before timelines existed.'
                    : 'Summarize this recording to get a timeline of what happened.'}
            </span>
            <Button
                size="sm"
                variant="outline"
                onClick={onSummarize}
                loading={summarizing}
                disabledReason={summarizeDisabledReason}
                data-attr={outdated ? 'vision-timeline-rebuild' : 'vision-timeline-summarize'}
            >
                <IconSparkles />
                {outdated ? 'Rebuild the timeline' : 'Summarize this recording'}
            </Button>
        </div>
    )
}

/** The recording's timeline on a rail: the summary's chapters and the idle gaps between them. */
export function QuillRecordingTimeline(props: QuillRecordingTimelineProps): JSX.Element {
    const { timeline, rows, currentTimeMs, onSeek } = props
    const currentIndex = currentRowIndex(rows, currentTimeMs)
    const hasHours = rows.some((row) => rowStartMs(row) >= HOUR_MS)
    const rowGrid = hasHours ? ROW_GRID_HOURS : ROW_GRID
    const formatTime = (ms: number): string => colonDelimitedDuration(Math.floor(ms / 1000), hasHours ? 3 : 2)
    const summary = timeline.summary as ReplayObservationApi

    return (
        <div className="flex flex-col py-1" data-attr="vision-recording-timeline">
            {rows.map((row, index) => {
                const startMs = rowStartMs(row)
                const isCurrent = index === currentIndex
                const passedAbove = startMs <= currentTimeMs
                const passedBelow = index < currentIndex
                const gapPx = index === 0 ? 0 : timelineGapPx(startMs - rowStartMs(rows[index - 1]))
                const inactive = row.kind === 'inactive'
                const rail = { first: index === 0, last: index === rows.length - 1, passedAbove, passedBelow }
                const timeCell = (
                    <span
                        className={cn(
                            'text-xs font-mono text-right',
                            row.kind === 'chapter' ? 'pt-2' : 'self-center py-1',
                            isCurrent ? 'text-primary font-semibold' : 'text-muted-foreground',
                            inactive && !isCurrent && 'opacity-70'
                        )}
                    >
                        {formatTime(startMs)}
                    </span>
                )
                return (
                    <Fragment key={`${row.kind}-${startMs}-${index}`}>
                        {gapPx > 0 && (
                            <div
                                className={rowGrid}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: gapPx }}
                            >
                                <span />
                                <QuillTimelineRail
                                    dot="none"
                                    passedAbove={passedAbove}
                                    passedBelow={passedAbove}
                                    isCurrent={false}
                                    dashed={rows[index - 1].kind === 'inactive'}
                                />
                            </div>
                        )}
                        {row.kind === 'chapter' ? (
                            <div
                                data-current-moment={isCurrent ? true : undefined}
                                className={cn(rowGrid, 'transition-colors', isCurrent && 'bg-fill-selected')}
                            >
                                {timeCell}
                                <QuillTimelineRail dot="chapter" isCurrent={isCurrent} alignTop {...rail} />
                                <Button
                                    size="row"
                                    left
                                    onClick={() => onSeek(row.chapter.startMs)}
                                    className="h-auto items-start gap-2 min-w-0 p-1 -mx-1 my-0.5"
                                    data-attr="vision-timeline-chapter"
                                >
                                    {row.chapter.hasFrame ? (
                                        <Tooltip>
                                            <TooltipTrigger render={<span className="flex shrink-0" />}>
                                                <QuillObservationThumbnail
                                                    observation={summary}
                                                    chapter={row.chapter.position}
                                                    className="w-20 shrink-0"
                                                    size="small"
                                                />
                                            </TooltipTrigger>
                                            <TooltipContent side="left" className="max-w-none p-1">
                                                <QuillObservationThumbnail
                                                    observation={summary}
                                                    chapter={row.chapter.position}
                                                    className="w-128 border-0"
                                                />
                                            </TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        <QuillObservationThumbnail
                                            observation={summary}
                                            chapter={row.chapter.position}
                                            className="w-20 shrink-0"
                                            size="small"
                                        />
                                    )}
                                    <span className="flex flex-col min-w-0 gap-0.5 text-left whitespace-normal">
                                        <span className="text-sm font-medium line-clamp-2">{row.chapter.title}</span>
                                        <span className="text-xs text-muted-foreground">
                                            {formatSpan(
                                                row.chapter.endMs - row.chapter.startMs - row.chapter.inactiveMs
                                            )}
                                            {row.chapter.inactiveMs >= MIN_INACTIVE_ROW_MS && (
                                                <span className="opacity-70">
                                                    {' '}
                                                    · {formatSpan(row.chapter.inactiveMs)} inactive
                                                </span>
                                            )}
                                        </span>
                                    </span>
                                </Button>
                            </div>
                        ) : row.kind === 'boundary' ? (
                            <div
                                data-current-moment={isCurrent ? true : undefined}
                                className={cn(rowGrid, isCurrent && 'bg-fill-selected')}
                                data-attr="vision-timeline-boundary"
                            >
                                {timeCell}
                                <QuillTimelineRail dot="boundary" isCurrent={false} {...rail} />
                                <Button
                                    variant="link-muted"
                                    size="inline"
                                    className="justify-start text-xs py-1"
                                    onClick={() => onSeek(row.atMs)}
                                >
                                    {row.edge === 'start' ? 'Session start' : 'Session end'}
                                </Button>
                            </div>
                        ) : (
                            <div
                                data-current-moment={isCurrent ? true : undefined}
                                className={rowGrid}
                                data-attr="vision-timeline-inactive"
                            >
                                {timeCell}
                                <QuillTimelineRail dot="none" isCurrent={false} dashed {...rail} />
                                <span className="text-xs text-muted-foreground italic py-1">
                                    Inactive for {formatSpan(row.endMs - row.startMs)}
                                </span>
                            </div>
                        )}
                    </Fragment>
                )
            })}
            <QuillSummaryNotice {...props} />
        </div>
    )
}
