import { useActions, useValues } from 'kea'
import { CSSProperties, useEffect, useRef, useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import type { ObservationSeekbarMark } from '../utils/observation'
import { currentMarkIndex, nextMarkAfter, timelineGapPx } from '../utils/observationTimeline'
import { ObservationMarkTooltip } from './ObservationSeekbarMarks'

const CURRENT_ROW_SELECTOR = '[data-current-moment]'

export function ObservationTimeline({
    sessionId,
    marks,
    onSeek,
}: {
    sessionId: string
    marks: ObservationSeekbarMark[]
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    const { currentPlayerTime } = useValues(sessionRecordingPlayerLogic)
    const logic = observationsDockLogic({ sessionId })
    const { hoveredMarkMs } = useValues(logic)
    const { setHoveredMark } = useActions(logic)
    const [follow, setFollow] = useState(true)
    // Pauses following so the user keeps their place once they scroll the current row out of view.
    const [scrolledAway, setScrolledAway] = useState(false)
    const listRef = useRef<HTMLDivElement>(null)

    const currentIndex = currentMarkIndex(marks, currentPlayerTime)
    const currentMs = currentIndex >= 0 ? marks[currentIndex].timestampMs : null
    const next = nextMarkAfter(marks, currentPlayerTime)

    const currentRow = (): HTMLElement | null =>
        listRef.current?.querySelector<HTMLElement>(CURRENT_ROW_SELECTOR) ?? null
    const currentRowInView = (): boolean => {
        const list = listRef.current
        const row = currentRow()
        if (!list || !row) {
            return true
        }
        const listRect = list.getBoundingClientRect()
        const rowRect = row.getBoundingClientRect()
        return rowRect.top >= listRect.top && rowRect.bottom <= listRect.bottom
    }
    const jumpToCurrent = (): void => {
        currentRow()?.scrollIntoView({ block: 'nearest' })
        setScrolledAway(false)
    }

    useEffect(() => {
        if (follow && !scrolledAway && currentMs !== null) {
            currentRow()?.scrollIntoView({ block: 'nearest' })
        }
    }, [currentMs, follow, scrolledAway])

    return (
        <div className="flex flex-col flex-1 min-h-0" data-attr="vision-observation-timeline">
            <div className="flex items-center gap-2 px-2 py-1 border-b">
                <span className="text-xs font-semibold uppercase tracking-wide text-secondary">Moments</span>
                <span className="text-xs text-secondary">{marks.length}</span>
                <div className="ml-auto flex items-center gap-1">
                    {currentMs !== null && (scrolledAway || !follow) && (
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={jumpToCurrent}
                            data-attr="vision-timeline-jump-to-now"
                        >
                            Jump to now
                        </LemonButton>
                    )}
                    <LemonSwitch
                        size="xsmall"
                        checked={follow}
                        onChange={setFollow}
                        label="Follow"
                        data-attr="vision-timeline-follow"
                    />
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronRight />}
                        tooltip="Next moment"
                        disabledReason={next ? undefined : 'No later moments'}
                        onClick={() => next && onSeek(next.timestampMs)}
                        data-attr="vision-timeline-next-moment"
                    />
                </div>
            </div>
            <div
                ref={listRef}
                className="flex-1 overflow-y-auto py-1"
                onScroll={() => follow && setScrolledAway(!currentRowInView())}
            >
                {marks.map((mark, index) => {
                    const passed = mark.timestampMs <= currentPlayerTime
                    const isCurrent = index === currentIndex
                    const gapPx = index === 0 ? 0 : timelineGapPx(mark.timestampMs - marks[index - 1].timestampMs)
                    const lead = mark.entries[0]
                    const scanners = [...new Set(mark.entries.map((entry) => entry.scannerName))].join(' · ')
                    return (
                        <div
                            key={mark.timestampMs}
                            data-current-moment={isCurrent ? true : undefined}
                            className={cn(
                                'grid grid-cols-[2.5rem_1rem_minmax(0,1fr)] gap-x-1.5 px-2 transition-colors',
                                isCurrent && 'bg-fill-highlight-50',
                                hoveredMarkMs === mark.timestampMs && 'bg-surface-secondary'
                            )}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ '--moment-gap': `${gapPx}px` } as CSSProperties}
                            onMouseEnter={() => setHoveredMark(mark.timestampMs)}
                            onMouseLeave={() => setHoveredMark(null)}
                        >
                            <span className="pt-[calc(var(--moment-gap)+0.5rem)] text-xs text-secondary font-mono text-right">
                                {colonDelimitedDuration(Math.floor(mark.timestampMs / 1000), null)}
                            </span>
                            <div className="flex flex-col items-center">
                                <span
                                    className={cn(
                                        'w-0.5 h-[calc(var(--moment-gap)+0.75rem)]',
                                        passed ? 'bg-accent' : 'bg-border'
                                    )}
                                />
                                <span
                                    className={cn(
                                        'w-2.5 h-2.5 rounded-full shrink-0',
                                        mark.flagged ? 'bg-accent' : passed ? 'bg-accent opacity-60' : 'bg-border',
                                        isCurrent && 'ring-2 ring-accent ring-offset-1'
                                    )}
                                />
                                <span
                                    className={cn(
                                        'w-0.5 flex-1',
                                        passed && index < currentIndex ? 'bg-accent' : 'bg-border'
                                    )}
                                />
                            </div>
                            <div className="pt-[var(--moment-gap)] pb-1 min-w-0">
                                <Tooltip title={<ObservationMarkTooltip mark={mark} />} placement="left">
                                    <LemonButton
                                        size="small"
                                        fullWidth
                                        onClick={() => onSeek(mark.timestampMs)}
                                        data-attr="vision-timeline-moment"
                                    >
                                        <span className="flex flex-col gap-0.5 min-w-0 text-left font-normal">
                                            <span className={cn('text-sm truncate', mark.flagged && 'font-semibold')}>
                                                {lead?.snippet ?? lead?.headline ?? scanners}
                                            </span>
                                            <span className="text-xs text-secondary truncate">
                                                {[scanners, lead?.snippet ? lead.headline : null]
                                                    .filter(Boolean)
                                                    .join(' · ')}
                                            </span>
                                        </span>
                                    </LemonButton>
                                </Tooltip>
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
