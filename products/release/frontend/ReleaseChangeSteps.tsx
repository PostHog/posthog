import { memo, useMemo } from 'react'

import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { ReleaseChange } from './releaseChanges'
import { Scale, x } from './releaseTracks'

const HIT = 10
const DIAMOND = 6

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

export const ReleaseChangeSteps = memo(function ReleaseChangeSteps({
    changes,
    scale,
    top,
    height,
    color,
}: {
    changes: ReleaseChange[]
    scale: Scale
    top: number
    height: number
    color: string
}): JSX.Element | null {
    const byDay = useMemo(() => changesByDay(changes, scale), [changes, scale])
    if (!byDay.size) {
        return null
    }
    return (
        <>
            {[...byDay.entries()].map(([day, group]) => (
                <Tooltip key={day}>
                    <TooltipTrigger
                        render={
                            <button
                                type="button"
                                aria-label={`${group.length} ${group.length === 1 ? 'change' : 'changes'} on ${dayjs(day).format('D MMM')}`}
                                className="group/step absolute z-20 flex cursor-default justify-center p-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                                style={{
                                    left: x(day, scale) - HIT / 2,
                                    top: top - DIAMOND / 2,
                                    width: HIT,
                                    height: height + DIAMOND / 2,
                                }}
                                onClick={(event) => event.stopPropagation()}
                                data-attr="release-change-step"
                            />
                        }
                    >
                        <span
                            className="absolute border-l-[1.5px] border-dashed group-hover/step:border-solid"
                            style={{ top: DIAMOND / 2, bottom: 0, borderColor: color }}
                        />
                        <span
                            className="absolute top-0 rotate-45 border border-background transition-transform group-hover/step:scale-150"
                            style={{ width: DIAMOND, height: DIAMOND, backgroundColor: color }}
                        />
                    </TooltipTrigger>
                    <TooltipContent sideOffset={6} className="max-w-72">
                        <div className="flex flex-col gap-2 text-xs">
                            {group.map((change) => (
                                <div key={change.key} className="flex flex-col gap-0.5">
                                    {change.lines.map((line) => (
                                        <span key={line}>{line}</span>
                                    ))}
                                    <span className="tabular-nums opacity-70">
                                        {`${dayjs(change.date).format('D MMM, HH:mm')} · ${change.who}`}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </TooltipContent>
                </Tooltip>
            ))}
        </>
    )
})
