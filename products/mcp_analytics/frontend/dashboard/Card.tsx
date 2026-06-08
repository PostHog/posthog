import { cn } from '@posthog/quill-primitives'

export const CARD_SURFACE = 'rounded-lg border border-primary bg-surface-primary'

export function Card({
    children,
    className,
    title,
}: {
    children: React.ReactNode
    className?: string
    title?: string
}): JSX.Element {
    return (
        <div className={cn(CARD_SURFACE, 'px-3.5 py-3', className)}>
            {title ? <h3 className="mb-3 text-sm font-medium text-primary">{title}</h3> : null}
            {children}
        </div>
    )
}

// Picks the right card body: a skeleton while the first load is in flight, an empty message when
// there's no data, otherwise the content. Guard clauses instead of a nested ternary at each call site.
export function CardState({
    loading,
    isEmpty,
    skeleton,
    empty,
    children,
}: {
    loading: boolean
    isEmpty: boolean
    skeleton: React.ReactNode
    empty: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    if (loading && isEmpty) {
        return <>{skeleton}</>
    }
    if (isEmpty) {
        return <>{empty}</>
    }
    return <>{children}</>
}
