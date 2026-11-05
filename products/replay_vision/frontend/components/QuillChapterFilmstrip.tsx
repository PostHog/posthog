import { useCallback, useEffect, useRef, useState } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { useResizeObserver } from 'lib/hooks/useResizeObserver'
import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'

import type { ReplayObservationApi } from '../generated/api.schemas'
import { MIN_INACTIVE_ROW_MS, currentRowIndex } from '../utils/recordingTimeline'
import { QuillObservationThumbnail } from './QuillObservationThumbnail'
import { QuillRecordingTimelineProps, QuillSummaryNotice } from './QuillRecordingTimeline'

const formatSpan = (ms: number): string => humanFriendlyDuration(ms / 1000, { maxUnits: 1 })

export function QuillChapterFilmstrip(props: QuillRecordingTimelineProps): JSX.Element {
    const { timeline, rows, currentTimeMs, onSeek } = props
    const [edges, setEdges] = useState({ atStart: true, atEnd: true })
    const stripRef = useRef<HTMLDivElement | null>(null)
    const { width, ref: observeStrip } = useResizeObserver<HTMLDivElement>()
    const currentIndex = currentRowIndex(rows, currentTimeMs)
    const hasHours = rows.some((row) => row.kind === 'chapter' && row.chapter.startMs >= 3_600_000)
    const formatTime = (ms: number): string => colonDelimitedDuration(Math.floor(ms / 1000), hasHours ? 3 : 2)
    const summary = timeline.summary as ReplayObservationApi

    const updateEdges = useCallback((): void => {
        const strip = stripRef.current
        if (!strip) {
            return
        }
        setEdges({
            atStart: strip.scrollLeft <= 1,
            atEnd: strip.scrollLeft + strip.clientWidth >= strip.scrollWidth - 1,
        })
    }, [])

    useEffect(updateEdges, [updateEdges, width, rows.length])

    const setStrip = useCallback(
        (element: HTMLDivElement | null): void => {
            stripRef.current = element
            observeStrip(element)
        },
        [observeStrip]
    )

    const page = (direction: -1 | 1): void => {
        const strip = stripRef.current
        strip?.scrollBy({ left: direction * strip.clientWidth * 0.8, behavior: 'smooth' })
    }

    return (
        <div className="flex flex-col" data-attr="vision-chapter-filmstrip">
            {rows.length > 0 && (
                <div className="flex items-center gap-1 px-1.5 py-2">
                    <Button
                        size="icon-xs"
                        tooltip="Earlier chapters"
                        aria-label="Earlier chapters"
                        disabledReason={edges.atStart ? 'At the start of the recording' : undefined}
                        onClick={() => page(-1)}
                        data-attr="vision-filmstrip-earlier"
                    >
                        <IconChevronLeft />
                    </Button>
                    <div
                        ref={setStrip}
                        onScroll={updateEdges}
                        className="flex flex-1 min-w-0 gap-2 overflow-x-auto snap-x snap-proximity [scrollbar-width:thin]"
                    >
                        {rows.map((row, index) => {
                            if (row.kind === 'boundary') {
                                return null
                            }
                            if (row.kind === 'inactive') {
                                return (
                                    <span
                                        key={`inactive-${row.startMs}`}
                                        className="flex w-11 shrink-0 flex-col items-center justify-center border-x border-dashed border-border text-center text-xxs text-muted-foreground"
                                        data-attr="vision-filmstrip-inactive"
                                    >
                                        <span>{formatSpan(row.endMs - row.startMs)}</span>
                                        <span>idle</span>
                                    </span>
                                )
                            }
                            const { chapter } = row
                            const isCurrent = index === currentIndex
                            const poster = (
                                <QuillObservationThumbnail
                                    observation={summary}
                                    chapter={chapter.position}
                                    className={cn('w-full', isCurrent && 'ring-2 ring-primary')}
                                    size="small"
                                >
                                    <span
                                        className={cn(
                                            'absolute bottom-1 left-1 rounded bg-black/70 px-1 font-mono text-xxs text-white',
                                            isCurrent && 'bg-primary'
                                        )}
                                    >
                                        {formatTime(chapter.startMs)}
                                    </span>
                                </QuillObservationThumbnail>
                            )
                            return (
                                <Button
                                    key={`chapter-${chapter.startMs}`}
                                    size="row"
                                    left
                                    onClick={() => onSeek(chapter.startMs)}
                                    data-current-moment={isCurrent ? true : undefined}
                                    className={cn(
                                        'h-auto min-w-0 shrink-0 grow basis-[9.5rem] max-w-[14rem] snap-start flex-col items-stretch gap-1 p-1 whitespace-normal',
                                        isCurrent && 'bg-fill-selected'
                                    )}
                                    data-attr="vision-filmstrip-chapter"
                                >
                                    {chapter.hasFrame ? (
                                        <Tooltip>
                                            <TooltipTrigger render={<span className="flex w-full" />}>
                                                {poster}
                                            </TooltipTrigger>
                                            <TooltipContent side="top" className="max-w-none p-1">
                                                <QuillObservationThumbnail
                                                    observation={summary}
                                                    chapter={chapter.position}
                                                    className="w-128 border-0"
                                                />
                                            </TooltipContent>
                                        </Tooltip>
                                    ) : (
                                        <span className="flex w-full">{poster}</span>
                                    )}
                                    <span className="text-sm font-medium line-clamp-2 text-left">{chapter.title}</span>
                                    <span className="text-xs text-muted-foreground text-left">
                                        {formatSpan(chapter.endMs - chapter.startMs - chapter.inactiveMs)}
                                        {chapter.inactiveMs >= MIN_INACTIVE_ROW_MS && (
                                            <span className="opacity-70">
                                                {' '}
                                                · {formatSpan(chapter.inactiveMs)} inactive
                                            </span>
                                        )}
                                    </span>
                                </Button>
                            )
                        })}
                    </div>
                    <Button
                        size="icon-xs"
                        tooltip="Later chapters"
                        aria-label="Later chapters"
                        disabledReason={edges.atEnd ? 'At the end of the recording' : undefined}
                        onClick={() => page(1)}
                        data-attr="vision-filmstrip-later"
                    >
                        <IconChevronRight />
                    </Button>
                </div>
            )}
            <QuillSummaryNotice {...props} />
        </div>
    )
}
