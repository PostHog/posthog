export function WatchPickRankBadge({ rank }: { rank: number }): JSX.Element {
    return (
        <span className="pointer-events-none absolute left-0 top-0 z-10 rounded-br bg-warning px-2 py-0.5 text-xs font-bold tabular-nums text-black">
            #{rank}
        </span>
    )
}
