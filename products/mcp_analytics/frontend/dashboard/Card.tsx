import { Card as QuillCard, CardContent, CardHeader, CardTitle, cn } from '@posthog/quill-primitives'

import { type TileErrorKind } from '../mcpDashboardOverviewLogic'

export function Card({
    children,
    className,
    flush = false,
    title,
}: {
    children: React.ReactNode
    className?: string
    /** Let a full-bleed child (table, chart) reach the card's edges, with no header-to-content gap. */
    flush?: boolean
    title?: string
}): JSX.Element {
    return (
        <QuillCard size="sm" flush={flush} className={className}>
            {title ? (
                <CardHeader>
                    <CardTitle>{title}</CardTitle>
                </CardHeader>
            ) : null}
            <CardContent className="flex flex-1 flex-col">{children}</CardContent>
        </QuillCard>
    )
}

// Picks the right card body: an error message when the load failed, a skeleton while the first load
// is in flight, an empty message when there's no data, otherwise the content. Guard clauses instead
// of a nested ternary at each call site.
export function CardState({
    loading,
    isEmpty,
    error,
    skeleton,
    empty,
    children,
}: {
    loading: boolean
    isEmpty: boolean
    // When set, the tile's load failed — show guidance instead of skeleton/empty/content.
    error?: TileErrorKind | null
    skeleton: React.ReactNode
    empty: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    if (error) {
        return <TileError kind={error} />
    }
    if (loading && isEmpty) {
        return <>{skeleton}</>
    }
    if (isEmpty) {
        return <>{empty}</>
    }
    return <>{children}</>
}

// Guidance shown when a tile's query failed: a too-large range points at a shorter range, everything
// else is a transient backend blip the user can retry.
export function tileErrorMessage(kind: TileErrorKind): string {
    return kind === 'memory'
        ? 'This range is too large to load. Try a shorter date range or narrower filters.'
        : "Couldn't load this data. Try again in a moment."
}

export function TileError({ kind, className }: { kind: TileErrorKind; className?: string }): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-1 items-center justify-center py-6 text-center text-[12px] text-secondary',
                className
            )}
        >
            {tileErrorMessage(kind)}
        </div>
    )
}
