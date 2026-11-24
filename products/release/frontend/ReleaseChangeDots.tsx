import { memo, useMemo } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { ReleaseChange } from './releaseChanges'
import { Scale, x } from './releaseTracks'

const DOT = 8
const GAP = 3

function changesByDay(changes: ReleaseChange[], scale: Scale): Map<string, ReleaseChange[]> {
    const end = scale.start.add(scale.days, 'day')
    const byDay = new Map<string, ReleaseChange[]>()
    for (const change of [...changes].sort((a, b) => a.date.localeCompare(b.date))) {
        const date = dayjs(change.date)
        if (date.isBefore(scale.start) || !date.isBefore(end)) {
            continue
        }
        const day = date.format('YYYY-MM-DD')
        byDay.set(day, [...(byDay.get(day) ?? []), change])
    }
    return byDay
}

export const ReleaseChangeDots = memo(function ReleaseChangeDots({
    changes,
    scale,
    center,
}: {
    changes: ReleaseChange[]
    scale: Scale
    center: number
}): JSX.Element | null {
    const byDay = useMemo(() => changesByDay(changes, scale), [changes, scale])
    if (!byDay.size) {
        return null
    }
    return (
        <>
            {[...byDay.entries()].flatMap(([day, group]) => {
                const step = Math.min(DOT + GAP, Math.max(0, (scale.day - DOT) / Math.max(1, group.length - 1)))
                const first = x(day, scale) + scale.day / 2 - ((group.length - 1) * step) / 2 - DOT / 2
                return group.map((change, index) => (
                    <Tooltip key={change.key}>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    aria-label={`Change on ${dayjs(change.date).format('D MMM, HH:mm')} by ${change.who}`}
                                    className="absolute z-20 cursor-default rounded-full border-[1.5px] border-background bg-foreground shadow-sm transition-transform hover:scale-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                                    style={{
                                        left: first + index * step,
                                        top: center - DOT / 2,
                                        width: DOT,
                                        height: DOT,
                                    }}
                                    onClick={(event) => event.stopPropagation()}
                                    data-attr="release-change-dot"
                                />
                            }
                        />
                        <TooltipContent sideOffset={6} className="max-w-64">
                            <div className="flex flex-col gap-0.5 text-xs">
                                {change.lines.map((line) => (
                                    <span key={line}>{line}</span>
                                ))}
                                <span className="tabular-nums opacity-70">
                                    {`${dayjs(change.date).format('D MMM, HH:mm')} · ${change.who}`}
                                </span>
                            </div>
                        </TooltipContent>
                    </Tooltip>
                ))
            })}
        </>
    )
})
