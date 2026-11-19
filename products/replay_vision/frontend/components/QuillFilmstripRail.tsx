import { cn } from 'lib/utils/css-classes'

/** Horizontal twin of `QuillTimelineRail`, drawn along the top of one filmstrip card. */
export function QuillFilmstripRail({
    dot,
    passedBefore,
    passedAfter,
    isCurrent,
    dashed = false,
    first = false,
    last = false,
}: {
    dot: boolean
    passedBefore: boolean
    passedAfter: boolean
    isCurrent: boolean
    dashed?: boolean
    first?: boolean
    last?: boolean
}): JSX.Element {
    const segment = (passed: boolean, hidden: boolean): string =>
        cn(
            'flex-1',
            hidden
                ? 'h-0.5'
                : dashed
                  ? cn('h-0 border-t-2 border-dotted', passed ? 'border-primary' : 'border-border')
                  : cn('h-0.5', passed ? 'bg-primary' : 'bg-border')
        )
    // Reaches across the card padding and the gap to the neighbouring cards.
    return (
        <span className="flex items-center -mx-2 h-5" aria-hidden>
            <span className={segment(passedBefore, first)} />
            {dot && (
                <span
                    className={cn(
                        'w-3 h-3 rounded-full shrink-0',
                        passedBefore ? 'bg-primary' : 'bg-background border-2 border-border',
                        isCurrent && 'ring-2 ring-primary ring-offset-1'
                    )}
                />
            )}
            <span className={segment(passedAfter, last)} />
        </span>
    )
}
