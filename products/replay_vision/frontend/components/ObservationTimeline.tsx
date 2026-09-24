import { useActions, useValues } from 'kea'
import { Fragment, useEffect } from 'react'

import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { observationsDockLogic } from '../logics/observationsDockLogic'
import type { ObservationSeekbarMark } from '../utils/observation'
import { currentMarkIndex, timelineGapPx } from '../utils/observationTimeline'
import { ObservationMarkTooltip } from './ObservationSeekbarMarks'

const ROW_GRID = 'grid grid-cols-[2.5rem_1rem_minmax(0,1fr)] gap-x-1.5'

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
    const currentIndex = currentMarkIndex(marks, currentPlayerTime)
    useEffect(() => () => setHoveredMark(null), [setHoveredMark])

    return (
        <div className="flex flex-col py-1" data-attr="vision-observation-timeline">
            {marks.map((mark, index) => {
                const passed = mark.timestampMs <= currentPlayerTime
                const isCurrent = index === currentIndex
                const gapPx = index === 0 ? 0 : timelineGapPx(mark.timestampMs - marks[index - 1].timestampMs)
                const lead = mark.entries[0]
                const railColor = passed ? 'bg-accent' : 'bg-border'
                return (
                    <Fragment key={mark.timestampMs}>
                        {gapPx > 0 && (
                            <div
                                className={cn(ROW_GRID, 'px-2')}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: gapPx }}
                            >
                                <span />
                                <span className={cn('w-0.5 h-full justify-self-center', railColor)} />
                            </div>
                        )}
                        <div
                            data-current-moment={isCurrent ? true : undefined}
                            className={cn(
                                ROW_GRID,
                                'px-2 py-1 transition-colors',
                                isCurrent && 'bg-fill-highlight-50',
                                hoveredMarkMs === mark.timestampMs && 'bg-surface-secondary'
                            )}
                            onMouseEnter={() => setHoveredMark(mark.timestampMs)}
                            onMouseLeave={() => setHoveredMark(null)}
                        >
                            <span
                                className={cn(
                                    'self-center text-xs font-mono text-right',
                                    isCurrent ? 'text-accent font-semibold' : 'text-secondary'
                                )}
                            >
                                {colonDelimitedDuration(Math.floor(mark.timestampMs / 1000), null)}
                            </span>
                            <div className="flex flex-col items-center -my-1">
                                <span className={cn('w-0.5 flex-1', railColor)} />
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
                            <Tooltip title={<ObservationMarkTooltip mark={mark} />} placement="left">
                                <LemonButton
                                    size="small"
                                    fullWidth
                                    onClick={() => onSeek(mark.timestampMs)}
                                    data-attr="vision-timeline-moment"
                                >
                                    <span
                                        className={cn(
                                            'text-sm truncate min-w-0 text-left',
                                            mark.flagged ? 'font-semibold' : 'font-normal'
                                        )}
                                    >
                                        {lead?.snippet ?? lead?.headline ?? lead?.scannerName}
                                    </span>
                                </LemonButton>
                            </Tooltip>
                        </div>
                    </Fragment>
                )
            })}
        </div>
    )
}
