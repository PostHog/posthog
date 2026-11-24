import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { ReleaseChange } from './releaseChanges'
import { Scale, x } from './releaseTracks'

const DOT = 9
const MAX_SHOWN = 5

export function ReleaseChangeDots({
    changes,
    scale,
    top,
}: {
    changes: ReleaseChange[]
    scale: Scale
    top: number
}): JSX.Element | null {
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
                                aria-label={`${group.length === 1 ? '1 change' : `${group.length} changes`} on ${dayjs(day).format('D MMM')}`}
                                className="absolute z-20 flex cursor-default items-center justify-center rounded-full border-[1.5px] border-background bg-foreground text-[9px] font-semibold leading-none text-background shadow-sm hover:scale-125 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
                                style={{
                                    left: x(day, scale) + scale.day / 2 - (group.length > 1 ? 7 : DOT / 2),
                                    top,
                                    width: group.length > 1 ? 14 : DOT,
                                    height: group.length > 1 ? 14 : DOT,
                                }}
                                onClick={(event) => event.stopPropagation()}
                                data-attr="release-change-dot"
                            >
                                {group.length > 1 ? group.length : null}
                            </button>
                        }
                    />
                    <TooltipContent sideOffset={6} className="max-w-72">
                        <div className="flex flex-col gap-2 py-0.5 text-xs">
                            <span className="font-medium">{dayjs(day).format('ddd, D MMM')}</span>
                            {[...group]
                                .reverse()
                                .slice(0, MAX_SHOWN)
                                .map((change) => (
                                    <div key={change.key} className="flex flex-col gap-0.5">
                                        <span className="tabular-nums opacity-70">
                                            {`${dayjs(change.date).format('HH:mm')} · ${change.who}`}
                                        </span>
                                        {change.lines.map((line) => (
                                            <span key={line}>{line}</span>
                                        ))}
                                    </div>
                                ))}
                            {group.length > MAX_SHOWN && (
                                <span className="opacity-70">{`${group.length - MAX_SHOWN} more changes this day`}</span>
                            )}
                        </div>
                    </TooltipContent>
                </Tooltip>
            ))}
        </>
    )
}
