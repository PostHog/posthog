/** A table of rows with a project value and the viewer's own value, under a three-column header. */
export function SettingsTable({
    firstColumn = 'Setting',
    children,
}: {
    firstColumn?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="@container overflow-hidden rounded border border-primary bg-surface-primary">
            <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,16rem)_minmax(0,18rem)] gap-3 px-4 py-1.5 text-xxs font-semibold uppercase tracking-wide text-secondary @min-[48rem]:grid">
                <span>{firstColumn}</span>
                <span>Project</span>
                <span>Mine</span>
            </div>
            {children}
        </div>
    )
}
