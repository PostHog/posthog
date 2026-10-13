import { Fragment } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import type { RecordingTimeline as RecordingTimelineData, TimelineRow } from '../utils/recordingTimeline'
import { MIN_INACTIVE_ROW_MS, currentRowIndex, rowStartMs, timelineGapPx } from '../utils/recordingTimeline'
import { ObservationThumbnail } from './ObservationThumbnail'
import { TimelineRail } from './TimelineRail'

export interface RecordingTimelineProps {
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

function SummaryNotice({
    timeline,
    onSummarize,
    summarizing,
    summarizeDisabledReason,
}: RecordingTimelineProps): JSX.Element | null {
    if (timeline.summaryState === 'ready') {
        return null
    }
    if (timeline.summaryState === 'pending') {
        return (
            <div
                className="flex items-center gap-2 px-3 py-2 text-xs text-secondary"
                data-attr="vision-timeline-pending"
            >
                <Spinner className="text-sm" /> Building the timeline of this recording…
            </div>
        )
    }
    const outdated = timeline.summaryState === 'outdated'
    return (
        <div className="flex flex-col items-start gap-2 px-3 py-3" data-attr="vision-timeline-cta">
            <span className="text-xs text-secondary">
                {outdated
                    ? 'This recording was summarized before timelines existed.'
                    : 'Summarize this recording to get a timeline of what happened.'}
            </span>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconSparkles />}
                onClick={onSummarize}
                loading={summarizing}
                disabledReason={summarizeDisabledReason}
                data-attr={outdated ? 'vision-timeline-rebuild' : 'vision-timeline-summarize'}
            >
                {outdated ? 'Rebuild the timeline' : 'Summarize this recording'}
            </LemonButton>
        </div>
    )
}

/** The recording's timeline on a rail: the summary's chapters and the idle gaps between them. */
export function RecordingTimeline(props: RecordingTimelineProps): JSX.Element {
    const { timeline, rows, currentTimeMs, onSeek } = props
    const currentIndex = currentRowIndex(rows, currentTimeMs)
    const hasHours = rows.some((row) => rowStartMs(row) >= HOUR_MS)
    const rowGrid = hasHours ? ROW_GRID_HOURS : ROW_GRID
    const formatTime = (ms: number): string => colonDelimitedDuration(Math.floor(ms / 1000), hasHours ? 3 : 2)

    return (
        <div className="flex flex-col py-1" data-attr="vision-recording-timeline">
            {rows.map((row, index) => {
                const startMs = rowStartMs(row)
                const isCurrent = index === currentIndex
                const passedAbove = startMs <= currentTimeMs
                const passedBelow = index < currentIndex
                const gapPx = index === 0 ? 0 : timelineGapPx(startMs - rowStartMs(rows[index - 1]))
                const inactive = row.kind === 'inactive'
                const timeCell = (
                    <span
                        className={cn(
                            'text-xs font-mono text-right',
                            row.kind === 'chapter' ? 'pt-2' : 'self-center py-1',
                            isCurrent ? 'text-accent font-semibold' : inactive ? 'text-tertiary' : 'text-secondary'
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
                                <TimelineRail
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
                                className={cn(rowGrid, 'transition-colors', isCurrent && 'bg-fill-highlight-50')}
                            >
                                {timeCell}
                                <TimelineRail
                                    dot="chapter"
                                    first={index === 0}
                                    last={index === rows.length - 1}
                                    passedAbove={passedAbove}
                                    passedBelow={passedBelow}
                                    isCurrent={isCurrent}
                                    alignTop
                                />
                                <button
                                    type="button"
                                    onClick={() => onSeek(row.chapter.startMs)}
                                    className="flex gap-2 min-w-0 text-left cursor-pointer rounded hover:bg-surface-secondary p-1 -mx-1 my-0.5"
                                    data-attr="vision-timeline-chapter"
                                >
                                    <Tooltip
                                        title={
                                            row.chapter.hasFrame ? (
                                                <ObservationThumbnail
                                                    observation={timeline.summary as ReplayObservationApi}
                                                    chapter={row.chapter.position}
                                                    className="w-128 border-0"
                                                />
                                            ) : undefined
                                        }
                                        placement="left"
                                        delayMs={300}
                                        containerClassName="max-w-none p-1"
                                    >
                                        <span className="flex shrink-0">
                                            <ObservationThumbnail
                                                observation={timeline.summary as ReplayObservationApi}
                                                chapter={row.chapter.position}
                                                className="w-20 shrink-0"
                                            />
                                        </span>
                                    </Tooltip>
                                    <span className="flex flex-col min-w-0 gap-0.5">
                                        <span className="text-sm font-medium line-clamp-2">{row.chapter.title}</span>
                                        <span className="text-xs text-secondary">
                                            {formatSpan(
                                                row.chapter.endMs - row.chapter.startMs - row.chapter.inactiveMs
                                            )}
                                            {row.chapter.inactiveMs >= MIN_INACTIVE_ROW_MS && (
                                                <span className="text-tertiary">
                                                    {' '}
                                                    · {formatSpan(row.chapter.inactiveMs)} inactive
                                                </span>
                                            )}
                                        </span>
                                    </span>
                                </button>
                            </div>
                        ) : row.kind === 'boundary' ? (
                            <div
                                data-current-moment={isCurrent ? true : undefined}
                                className={cn(rowGrid, isCurrent && 'bg-fill-highlight-50')}
                                data-attr="vision-timeline-boundary"
                            >
                                {timeCell}
                                <TimelineRail
                                    dot="boundary"
                                    first={index === 0}
                                    last={index === rows.length - 1}
                                    passedAbove={passedAbove}
                                    passedBelow={passedBelow}
                                    isCurrent={false}
                                />
                                <button
                                    type="button"
                                    onClick={() => onSeek(row.atMs)}
                                    className="text-xs text-secondary text-left py-1 cursor-pointer hover:text-primary"
                                >
                                    {row.edge === 'start' ? 'Session start' : 'Session end'}
                                </button>
                            </div>
                        ) : (
                            <div
                                data-current-moment={isCurrent ? true : undefined}
                                className={rowGrid}
                                data-attr="vision-timeline-inactive"
                            >
                                {timeCell}
                                <TimelineRail
                                    dot="none"
                                    first={index === 0}
                                    last={index === rows.length - 1}
                                    passedAbove={passedAbove}
                                    passedBelow={passedBelow}
                                    isCurrent={false}
                                    dashed
                                />
                                <span className="text-xs text-tertiary italic py-1">
                                    Inactive for {formatSpan(row.endMs - row.startMs)}
                                </span>
                            </div>
                        )}
                    </Fragment>
                )
            })}
            <SummaryNotice {...props} />
        </div>
    )
}
