import { cn } from 'lib/utils/css-classes'

const HEIGHTS = { large: 'h-10', medium: 'h-8', small: 'h-7' } as const

export type StoryBarSize = keyof typeof HEIGHTS

/** A thick bar with its label and value written on it, the one way every list in the story draws a ranking. */
export function StoryBar({
    label,
    value,
    fraction,
    index,
    emphasized = false,
    muted = false,
    size = 'large',
    title,
}: {
    label: React.ReactNode
    value: string
    /** How much of the track the bar fills, from 0 to 1. */
    fraction: number
    /** The row's place in the list, which staggers its entrance. */
    index: number
    /** The leader is drawn solid, with its text dark wherever the fill sits under it. */
    emphasized?: boolean
    /** A catch-all row such as "Other" reads quieter than the named ones. */
    muted?: boolean
    size?: StoryBarSize
    title?: string
}): JSX.Element {
    const delay = `${index * 80}ms`
    const filled = Math.max(2, fraction * 100)
    const content = (
        <>
            <span className="flex min-w-0 flex-1 items-center gap-2">{label}</span>
            <span className="shrink-0">{value}</span>
        </>
    )
    return (
        <li
            className={cn(
                'MCPWrapped__rise relative overflow-hidden rounded-lg bg-white/15 text-sm font-semibold tabular-nums',
                HEIGHTS[size],
                muted && 'opacity-75'
            )}
            style={{ animationDelay: delay }}
            title={title}
        >
            <span
                className={cn(
                    'MCPWrapped__grow-x absolute inset-y-0 left-0 rounded-lg',
                    emphasized ? 'bg-white' : 'bg-white/30'
                )}
                style={{ width: `${filled}%`, animationDelay: delay }}
            />
            <span className="relative flex h-full items-center gap-2 px-3">{content}</span>
            {emphasized && (
                // A dark copy of the text, cut to the solid fill, so the label stays readable however far the
                // fill reaches: dark on the fill, white past it.
                <span
                    aria-hidden
                    className="MCPWrapped__reveal-x absolute inset-0 flex items-center gap-2 px-3 text-black/80"
                    style={{ clipPath: `inset(0 ${100 - filled}% 0 0)`, animationDelay: delay }}
                >
                    {content}
                </span>
            )}
        </li>
    )
}
