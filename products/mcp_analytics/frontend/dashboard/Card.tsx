import { LemonButton } from '@posthog/lemon-ui'
import { Card as QuillCard, CardAction, CardContent, CardHeader, CardTitle, cn } from '@posthog/quill-primitives'

export function Card({
    children,
    className,
    flush = false,
    title,
    action,
}: {
    children: React.ReactNode
    className?: string
    /** Let a full-bleed child (table, chart) reach the card's edges, with no header-to-content gap. */
    flush?: boolean
    title?: string
    /** Control shown at the top right of the header. */
    action?: React.ReactNode
}): JSX.Element {
    return (
        <QuillCard size="sm" flush={flush} className={className}>
            {title ? (
                <CardHeader className={action ? 'flex flex-wrap items-start justify-between gap-2' : undefined}>
                    <CardTitle>{title}</CardTitle>
                    {action ? <CardAction>{action}</CardAction> : null}
                </CardHeader>
            ) : null}
            {/* min-h-0 lets a height-constrained card's content shrink instead of overflowing the card's clip. */}
            <CardContent className="flex flex-1 flex-col min-h-0">{children}</CardContent>
        </QuillCard>
    )
}

// Picks the right card body: an error with a retry when the load failed, a skeleton while the first
// load is in flight, an empty message when there's no data, otherwise the content. Every state
// shares `className`, so give it the content's min height and swapping states doesn't move the layout.
export function CardState({
    loading,
    isEmpty,
    failed = false,
    onRetry,
    skeleton,
    empty,
    className,
    children,
}: {
    loading: boolean
    isEmpty: boolean
    failed?: boolean
    onRetry?: () => void
    skeleton: React.ReactNode
    empty: React.ReactNode
    className?: string
    children: React.ReactNode
}): JSX.Element {
    const bodyClassName = cn('flex min-h-0 flex-1 flex-col', className)
    if (failed) {
        return (
            <div className={cn(bodyClassName, 'items-center justify-center py-6')}>
                <CardError onRetry={onRetry} />
            </div>
        )
    }
    if (loading && isEmpty) {
        return <div className={bodyClassName}>{skeleton}</div>
    }
    if (isEmpty) {
        return <div className={bodyClassName}>{empty}</div>
    }
    return (
        // Dim while refreshing so date/tool changes give visible feedback.
        <div aria-busy={loading} className={cn(bodyClassName, 'transition-opacity', loading && 'opacity-50')}>
            {children}
        </div>
    )
}

export function CardError({ onRetry }: { onRetry?: () => void }): JSX.Element {
    return (
        <div className="flex flex-col items-center gap-2 text-center text-[12px] text-secondary">
            <span>Couldn&apos;t load this data. Try again, or pick a shorter date range.</span>
            {onRetry ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={(event) => {
                        // A KPI tile is a link, so keep the retry click from following it.
                        event.preventDefault()
                        event.stopPropagation()
                        onRetry()
                    }}
                    data-attr="mcp-dashboard-card-retry"
                >
                    Try again
                </LemonButton>
            ) : null}
        </div>
    )
}
