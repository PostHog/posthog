import { cn } from 'lib/utils/css-classes'

export function WatchPickRankBadge({
    rank,
    size = 'medium',
}: {
    rank: number
    size?: 'small' | 'medium'
}): JSX.Element {
    return (
        <span
            className={cn(
                'pointer-events-none absolute left-0 top-0 z-10 rounded-br bg-warning font-bold tabular-nums text-black',
                size === 'small' ? 'px-1 text-xxs leading-4' : 'px-2 py-0.5 text-xs'
            )}
        >
            #{rank}
        </span>
    )
}
