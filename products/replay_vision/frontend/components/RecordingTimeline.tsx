import { IconSparkles } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import type {
    RecordingTimeline as RecordingTimelineData,
    TimelineMarker,
    TimelineRow,
} from '../utils/recordingTimeline'
import { currentRowIndex } from '../utils/recordingTimeline'
import { TimelineChapterRow } from './TimelineChapterRow'
import { TimelineMarkerChip } from './TimelineMarkerChip'

export interface RecordingTimelineProps {
    timeline: RecordingTimelineData
    rows: TimelineRow[]
    currentTimeMs: number
    onSeek: (timestampMs: number) => void
    onMarkerClick: (marker: TimelineMarker) => void
    onSummarize: () => void
    summarizing: boolean
    summarizeDisabledReason?: string | null
    onRebuild: () => void
    rebuilding: boolean
}

const formatTime = (ms: number): string => colonDelimitedDuration(Math.floor(ms / 1000), null)

function SummaryNotice({
    timeline,
    onSummarize,
    summarizing,
    summarizeDisabledReason,
    onRebuild,
    rebuilding,
}: Omit<RecordingTimelineProps, 'rows' | 'currentTimeMs' | 'onSeek' | 'onMarkerClick'>): JSX.Element | null {
    if (timeline.summaryState === 'ready') {
        return null
    }
    if (timeline.summaryState === 'pending') {
        return (
            <div
                className="flex items-center gap-2 px-3 py-2 text-xs text-secondary"
                data-attr="vision-timeline-pending"
            >
                <Spinner className="text-sm" /> Building the breakdown of this recording…
            </div>
        )
    }
    const outdated = timeline.summaryState === 'outdated'
    return (
        <div className="flex flex-col items-start gap-2 px-3 py-3" data-attr="vision-timeline-cta">
            <span className="text-xs text-secondary">
                {outdated
                    ? 'This recording was summarized before breakdowns existed.'
                    : 'Summarize this recording to get a breakdown of what happened, part by part.'}
            </span>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconSparkles />}
                onClick={outdated ? onRebuild : onSummarize}
                loading={outdated ? rebuilding : summarizing}
                disabledReason={summarizeDisabledReason}
                data-attr={outdated ? 'vision-timeline-rebuild' : 'vision-timeline-summarize'}
            >
                {outdated ? 'Rebuild the breakdown' : 'Summarize this recording'}
            </LemonButton>
        </div>
    )
}

/** The recording's breakdown: summary chapters with idle gaps between them, and every scan's key moment. */
export function RecordingTimeline(props: RecordingTimelineProps): JSX.Element {
    const { timeline, rows, currentTimeMs, onSeek, onMarkerClick } = props
    const currentIndex = currentRowIndex(rows, currentTimeMs)
    return (
        <div className="flex flex-col" data-attr="vision-recording-timeline">
            {rows.map((row, index) => {
                const isCurrent = index === currentIndex
                if (row.kind === 'chapter') {
                    return (
                        <TimelineChapterRow
                            key={`chapter-${row.chapter.position}`}
                            summary={timeline.summary as ReplayObservationApi}
                            chapter={row.chapter}
                            markers={row.markers}
                            isCurrent={isCurrent}
                            onSeek={onSeek}
                            onMarkerClick={onMarkerClick}
                        />
                    )
                }
                if (row.kind === 'inactive') {
                    return (
                        <div
                            key={`inactive-${row.startMs}`}
                            data-current-moment={isCurrent ? true : undefined}
                            className={cn(
                                'flex items-center gap-2 px-3 py-1 text-xs text-tertiary bg-surface-secondary',
                                'bg-[repeating-linear-gradient(135deg,transparent_0_6px,var(--color-border-primary)_6px_7px)]'
                            )}
                            data-attr="vision-timeline-inactive"
                        >
                            <span className="font-mono w-10 text-right shrink-0">{formatTime(row.startMs)}</span>
                            <span>
                                Inactive for {humanFriendlyDuration((row.endMs - row.startMs) / 1000, { maxUnits: 1 })}
                            </span>
                        </div>
                    )
                }
                return (
                    <div
                        key={`marker-${row.marker.observationId}`}
                        data-current-moment={isCurrent ? true : undefined}
                        className={cn('flex items-center gap-2 px-3 py-1', isCurrent && 'bg-fill-highlight-50')}
                    >
                        <span className="font-mono text-xs text-secondary w-10 text-right shrink-0">
                            {formatTime(row.marker.timestampMs)}
                        </span>
                        <TimelineMarkerChip
                            marker={row.marker}
                            onClick={() => {
                                onSeek(row.marker.timestampMs)
                                onMarkerClick(row.marker)
                            }}
                        />
                    </div>
                )
            })}
            <SummaryNotice {...props} />
        </div>
    )
}
