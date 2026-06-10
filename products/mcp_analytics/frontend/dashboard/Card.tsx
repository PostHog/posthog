import { Card as QuillCard, CardContent, CardHeader, CardTitle } from '@posthog/quill-primitives'

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
        <QuillCard size="sm" className={className}>
            {title ? (
                <CardHeader>
                    <CardTitle>{title}</CardTitle>
                </CardHeader>
            ) : null}
            <CardContent className="flex flex-1 flex-col">{children}</CardContent>
        </QuillCard>
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
