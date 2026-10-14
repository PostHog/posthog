import { cn } from 'lib/utils/css-classes'

export type TimelineRailDot = 'chapter' | 'boundary' | 'none'

/** The rail cell of one timeline row: the line through it, and the dot that marks where the row sits. */
export function TimelineRail({
    dot,
    passedAbove,
    passedBelow,
    isCurrent,
    dashed = false,
    alignTop = false,
    first = false,
    last = false,
}: {
    dot: TimelineRailDot
    passedAbove: boolean
    passedBelow: boolean
    isCurrent: boolean
    /** Idle time, where the user was not there to be followed. */
    dashed?: boolean
    /** Puts the dot level with the first line of the row rather than its middle, for tall rows. */
    alignTop?: boolean
    /** The rail starts and stops at the rows at its ends, rather than running out of the list. */
    first?: boolean
    last?: boolean
}): JSX.Element {
    const segment = (passed: boolean, grow: boolean, hidden: boolean): string =>
        cn(
            grow ? 'flex-1' : 'h-3.5 shrink-0',
            hidden
                ? 'w-0.5'
                : dashed
                  ? cn('w-0 border-l-2 border-dotted', passed ? 'border-accent' : 'border-secondary')
                  : cn('w-0.5', passed ? 'bg-accent' : 'bg-border')
        )
    return (
        <div className="flex flex-col items-center self-stretch">
            <span className={segment(passedAbove, !alignTop, first)} />
            {dot !== 'none' && (
                <span
                    className={cn(
                        'rounded-full shrink-0',
                        dot === 'chapter' ? 'w-3 h-3' : 'w-2 h-2',
                        dot === 'boundary'
                            ? cn('rounded-sm', passedAbove ? 'bg-accent' : 'bg-border-bold')
                            : passedAbove
                              ? 'bg-accent'
                              : 'bg-surface-primary border-2 border-primary',
                        isCurrent && 'ring-2 ring-accent ring-offset-1'
                    )}
                />
            )}
            <span className={segment(passedBelow, true, last)} />
        </div>
    )
}
