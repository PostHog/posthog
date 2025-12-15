import { IconChevronLeft, IconChevronRight } from '@posthog/icons'

import { cn } from 'lib/utils/css-classes'

interface LogRowScrollButtonsProps {
    onStartScrolling: (direction: 'left' | 'right') => void
    onStopScrolling: () => void
    className?: string
}

export function LogRowScrollButtons({
    onStartScrolling,
    onStopScrolling,
    className,
}: LogRowScrollButtonsProps): JSX.Element {
    return (
        <div
            className={cn(
                'absolute right-0 top-0 bottom-0 flex items-center opacity-0 transition-opacity bg-gradient-to-l from-bg-light via-bg-light to-transparent pl-4 pr-1',
                className ?? 'group-hover:opacity-100'
            )}
            onMouseDown={(e) => e.stopPropagation()}
        >
            <button
                type="button"
                aria-label="Scroll left"
                className="p-1 text-muted hover:text-default cursor-pointer select-none"
                onMouseDown={(e) => {
                    e.preventDefault()
                    onStartScrolling('left')
                }}
                onMouseUp={onStopScrolling}
                onMouseLeave={onStopScrolling}
            >
                <IconChevronLeft className="text-lg" />
            </button>
            <button
                type="button"
                aria-label="Scroll right"
                className="p-1 text-muted hover:text-default cursor-pointer select-none"
                onMouseDown={(e) => {
                    e.preventDefault()
                    onStartScrolling('right')
                }}
                onMouseUp={onStopScrolling}
                onMouseLeave={onStopScrolling}
            >
                <IconChevronRight className="text-lg" />
            </button>
        </div>
    )
}
