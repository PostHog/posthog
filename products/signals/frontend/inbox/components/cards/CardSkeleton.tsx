import clsx from 'clsx'

import { LemonSkeleton } from '@posthog/lemon-ui'

interface CardSkeletonProps {
    /** Number of rows to render. */
    count?: number
    /** Row style: bordered rows joined into a list, or freestanding cards. */
    variant?: 'rows' | 'cards'
    /** Freestanding cards use a dashed border to match report cards; pass false for PR cards (solid). */
    dashed?: boolean
}

export function CardSkeleton({ count = 4, variant = 'rows', dashed = true }: CardSkeletonProps): JSX.Element {
    if (variant === 'cards') {
        return (
            <div className="flex flex-col gap-1.5">
                {Array.from({ length: count }).map((_, i) => (
                    <SkeletonRow key={i} rounded dashed={dashed} />
                ))}
            </div>
        )
    }

    return (
        <div className="overflow-hidden rounded border border-primary bg-surface-primary">
            {Array.from({ length: count }).map((_, i) => (
                <SkeletonRow key={i} bordered />
            ))}
        </div>
    )
}

function SkeletonRow({
    rounded,
    bordered,
    dashed,
}: {
    rounded?: boolean
    bordered?: boolean
    dashed?: boolean
}): JSX.Element {
    return (
        <div
            className={clsx(
                'flex w-full items-stretch gap-3 px-4 py-3.5',
                rounded && 'rounded border border-primary bg-surface-primary',
                rounded && dashed && 'border-dashed',
                bordered && 'border-b border-primary last:border-b-0'
            )}
        >
            {/* Matches the report card's square priority badge (`size-6`). */}
            <LemonSkeleton className="size-6 shrink-0 rounded-sm" />
            <div className="flex min-w-0 flex-1 flex-col gap-2 py-0.5">
                <LemonSkeleton className="h-3.5 w-3/5" />
                <LemonSkeleton className="h-3 w-4/5" />
                <div className="flex items-center gap-1.5 pt-0.5">
                    <LemonSkeleton className="h-3.5 w-16" />
                    <LemonSkeleton className="h-3.5 w-20" />
                </div>
            </div>
            <div className="flex shrink-0 items-center gap-2 self-center">
                <LemonSkeleton className="h-3 w-10" />
                <LemonSkeleton className="h-7 w-16 rounded" />
            </div>
        </div>
    )
}
