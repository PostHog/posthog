import { Badge } from '@posthog/quill'

export function QuillHighlightPickRankBadge({ rank }: { rank: number }): JSX.Element {
    return (
        <Badge
            variant="warning"
            className="pointer-events-none absolute left-0 top-0 z-10 rounded-none rounded-br px-1 font-bold tabular-nums"
        >
            #{rank}
        </Badge>
    )
}
