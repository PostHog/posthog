import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import type { TimelineChapter, TimelineMarker } from '../utils/recordingTimeline'
import { MIN_INACTIVE_ROW_MS } from '../utils/recordingTimeline'
import { ObservationThumbnail } from './ObservationThumbnail'
import { TimelineMarkerChip } from './TimelineMarkerChip'

const formatTime = (ms: number): string => colonDelimitedDuration(Math.floor(ms / 1000), null)
const formatSpan = (ms: number): string => humanFriendlyDuration(ms / 1000, { maxUnits: 1 })

export interface TimelineChapterRowProps {
    summary: ReplayObservationApi
    chapter: TimelineChapter
    markers: TimelineMarker[]
    isCurrent: boolean
    onSeek: (timestampMs: number) => void
    onMarkerClick: (marker: TimelineMarker) => void
}

/** One summary chapter: its frame, start time and heading, with the key moments other scans found inside it. */
export function TimelineChapterRow({
    summary,
    chapter,
    markers,
    isCurrent,
    onSeek,
    onMarkerClick,
}: TimelineChapterRowProps): JSX.Element {
    const activeMs = chapter.endMs - chapter.startMs - chapter.inactiveMs
    return (
        <div
            data-current-moment={isCurrent ? true : undefined}
            className={cn(
                'relative border-l-2 transition-colors',
                isCurrent ? 'border-accent bg-fill-highlight-50' : 'border-transparent hover:bg-surface-secondary'
            )}
        >
            <button
                type="button"
                onClick={() => onSeek(chapter.startMs)}
                className="flex w-full gap-2 px-3 py-2 text-left cursor-pointer"
                data-attr="vision-timeline-chapter"
            >
                <ObservationThumbnail observation={summary} chapter={chapter.position} className="w-24 shrink-0" />
                <span className="flex flex-col min-w-0 gap-0.5">
                    <span className="flex items-baseline gap-1.5 text-xs text-secondary">
                        <span className={cn('font-mono', isCurrent && 'text-accent font-semibold')}>
                            {formatTime(chapter.startMs)}
                        </span>
                        <span>{formatSpan(activeMs)}</span>
                        {chapter.inactiveMs >= MIN_INACTIVE_ROW_MS && (
                            <span className="text-tertiary">· {formatSpan(chapter.inactiveMs)} inactive</span>
                        )}
                    </span>
                    <span className="text-sm font-medium line-clamp-2">{chapter.title}</span>
                </span>
            </button>
            {markers.length > 0 && (
                <div className="flex flex-wrap gap-1 px-3 pb-2 pl-[8.5rem]">
                    {markers.map((marker) => (
                        <TimelineMarkerChip
                            key={marker.observationId}
                            marker={marker}
                            onClick={() => {
                                onSeek(marker.timestampMs)
                                onMarkerClick(marker)
                            }}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}
