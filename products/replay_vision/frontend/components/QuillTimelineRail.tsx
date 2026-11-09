import { cn } from 'lib/utils/css-classes'

import type { TimelineRailDot } from './TimelineRail'

/** The rail cell of one timeline row: the line through it, and the dot that marks where the row sits. */
export function QuillTimelineRail({
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
    dashed?: boolean
    alignTop?: boolean
    first?: boolean
    last?: boolean
}): JSX.Element {
    const segment = (passed: boolean, grow: boolean, hidden: boolean): string =>
        cn(
            grow ? 'flex-1' : 'h-3.5 shrink-0',
            hidden
                ? 'w-0.5'
                : dashed
                  ? cn('w-0 border-l-2 border-dotted', passed ? 'border-primary' : 'border-border')
                  : cn('w-0.5', passed ? 'bg-primary' : 'bg-border')
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
                            ? cn('rounded-sm', passedAbove ? 'bg-primary' : 'bg-border')
                            : passedAbove
                              ? 'bg-primary'
                              : 'bg-background border-2 border-border',
                        isCurrent && 'ring-2 ring-primary ring-offset-1'
                    )}
                />
            )}
            <span className={segment(passedBelow, true, last)} />
        </div>
    )
}
