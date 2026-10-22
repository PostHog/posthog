import { useVirtualizer } from '@tanstack/react-virtual'
import { useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import { TimelineData, TimelineNode, parentNodes, timelineTicks, visibleTimelineRows } from '../lib/ciTimeline'
import { timeAxis } from '../lib/pullRequestTimeline'
import { CITimelineRow, CI_TIMELINE_COLUMNS, CI_TIMELINE_ROW_HEIGHT_PX, CI_TIMELINE_SCALE } from './CITimelineRow'

const MAX_TICKS = 8

/** Failing rows start expanded so the first view shows what broke. */
export function CITimeline({ timeline }: { timeline: TimelineData }): JSX.Element {
    // Only what the person toggled is stored, so rows that arrive later still open by the failing rule.
    const [toggled, setToggled] = useState<ReadonlyMap<string, boolean>>(new Map())
    const isExpanded = (node: TimelineNode): boolean => toggled.get(node.id) ?? node.status === 'failure'
    const rows = visibleTimelineRows(timeline.nodes, isExpanded)
    // A job a re-run carried over from an earlier attempt starts before the axis, which clips it to the track.
    const axis = timeAxis(timeline.startMs, timeline.endMs)
    const ticks = timelineTicks((timeline.endMs - timeline.startMs) / 1000, MAX_TICKS)
    const tickPosition = (seconds: number): string => axis.position(timeline.startMs + seconds * 1000)

    // Expand all on a matrix-heavy push opens thousands of step rows, so only the rows in view mount.
    const scrollRef = useRef<HTMLDivElement>(null)
    const virtualizer = useVirtualizer({
        count: rows.length,
        getScrollElement: () => scrollRef.current,
        estimateSize: () => CI_TIMELINE_ROW_HEIGHT_PX,
        getItemKey: (index) => rows[index].node.id,
        overscan: 10,
        // The sticky tick header sits above the first row inside the scroll container.
        scrollMargin: CI_TIMELINE_ROW_HEIGHT_PX,
    })

    const setAll = (expanded: boolean): void =>
        setToggled(new Map(parentNodes(timeline.nodes).map((node) => [node.id, expanded])))
    const toggle = (node: TimelineNode): void =>
        setToggled((previous) => new Map(previous).set(node.id, !isExpanded(node)))

    return (
        <div className="overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="flex items-center gap-2 border-b border-primary px-2 py-1.5">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setAll(true)}
                    data-attr="engineering-analytics-ci-timeline-expand-all"
                >
                    Expand all
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setAll(false)}
                    data-attr="engineering-analytics-ci-timeline-collapse-all"
                >
                    Collapse all
                </LemonButton>
            </div>
            <div ref={scrollRef} className="max-h-[70vh] overflow-y-auto">
                <div
                    className={cn(
                        'sticky top-0 z-10 grid h-7 border-b border-primary bg-surface-secondary text-[11px] font-semibold text-tertiary',
                        CI_TIMELINE_COLUMNS
                    )}
                >
                    <div className="flex items-center justify-between border-r border-primary px-2">
                        <span>Name</span>
                        <span>Duration</span>
                    </div>
                    <div className="relative">
                        <div className={CI_TIMELINE_SCALE}>
                            {ticks.map((seconds) => (
                                <span
                                    key={seconds}
                                    className={cn(
                                        'absolute top-1/2 -translate-y-1/2 font-normal tabular-nums whitespace-nowrap',
                                        seconds > 0 && '-translate-x-1/2'
                                    )}
                                    style={{ left: tickPosition(seconds) }}
                                >
                                    {humanFriendlyDuration(seconds)}
                                </span>
                            ))}
                        </div>
                    </div>
                </div>
                <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
                    <div className={cn('pointer-events-none absolute inset-0 grid', CI_TIMELINE_COLUMNS)}>
                        <div />
                        <div className="relative">
                            <div className={CI_TIMELINE_SCALE}>
                                {ticks.map((seconds) => (
                                    <span
                                        key={seconds}
                                        className="absolute inset-y-0 border-l border-primary opacity-60"
                                        style={{ left: tickPosition(seconds) }}
                                    />
                                ))}
                            </div>
                        </div>
                    </div>
                    {virtualizer.getVirtualItems().map((item) => {
                        const row = rows[item.index]
                        return (
                            <div
                                key={item.key}
                                className="absolute inset-x-0 top-0"
                                style={{ transform: `translateY(${item.start - CI_TIMELINE_ROW_HEIGHT_PX}px)` }}
                            >
                                <CITimelineRow
                                    row={row}
                                    axis={axis}
                                    expanded={isExpanded(row.node)}
                                    onToggle={() => toggle(row.node)}
                                />
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
