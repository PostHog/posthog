// PROTOTYPE (throwaway): what a card on the overview shows before it has data, with the step that fills it.
export function EmptyInsight({
    title,
    detail,
    children,
}: {
    title: string
    detail: string
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex h-full min-h-40 flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-6 text-center">
            <span className="text-sm font-medium">{title}</span>
            <span className="max-w-sm text-xs text-muted-foreground">{detail}</span>
            {children ? <div className="mt-1 flex flex-wrap justify-center gap-2">{children}</div> : null}
        </div>
    )
}
